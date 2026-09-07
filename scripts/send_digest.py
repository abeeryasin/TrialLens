"""The daily digest's scheduled job (step 12).

Runs weekdays (.github/workflows/digest.yml). Reads the window through
FastAPI — the only door, sec. 5, and this script deliberately reaches the
database for one thing only: its own run record.

**Each digest reports one whole weekday, and the weekend is dropped.**
Tue-Fri report the previous calendar day; Monday reports Friday. Measured
over the record's first ten days, Saturday and Sunday carry 1-7 changed
trials against a weekday's 65-136 and have never yet carried a single
primary-outcome change, so nothing of substance goes with them.

Whole days rather than a rolling 24 hours is what makes that possible at
all: "everything since Friday 07:00" necessarily contains the weekend, and
clipping it to Monday 00:00 would silently drop a whole working day of
Friday. The run record still matters — a run that did not send does not
advance the window, so a failed Tuesday is caught up by Wednesday rather
than mailed to nobody.

**And an empty window sends nothing.** A mail that says "nothing happened"
teaches the reader to skim, and then the one that matters is skimmed too.

**Credential handling.** This process holds a database URL and a Resend API
key. Neither may reach a repo file (sec. 2) or an error message: the key is
read from the environment, and every exception is scrubbed through
api/safe_errors.describe() before it is printed or written to a column that
GET /ops/status will later put on a page. That is the second door the
2026-09-05 leak came through, and it is now the third job to close it.

Run manually (sends a real email — the free suite covers everything else):
    .venv/bin/python scripts/send_digest.py
    .venv/bin/python scripts/send_digest.py --dry-run   # composes, sends nothing
"""
import argparse
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env.local")
load_dotenv(ROOT / ".env")

from api.digest import DEFAULT_APP_URL, compose  # noqa: E402
from api.safe_errors import describe  # noqa: E402

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
APP_URL = os.environ.get("APP_URL", DEFAULT_APP_URL)

RESEND_ENDPOINT = "https://api.resend.com/emails"

# Resend's shared sender. It needs no DNS and no domain purchase, and its one
# restriction — it can only deliver to the address on the Resend account —
# happens to be exactly this product's shape: TrialLens is a single
# researcher's tool and the digest goes to that researcher. Verified against
# Resend's own docs 2026-09-07. If TrialLens ever mails a second person, this
# is the line that has to change, and it will fail loudly with a 403 rather
# than silently not arrive.
DEFAULT_FROM = "TrialLens <onboarding@resend.dev>"

# /investigate takes whole days. Windows here are whole days by
# construction, so rounding (not ceiling) keeps a few minutes of scheduler
# drift from silently re-reporting a day the last mail already covered.
def window_days(since: datetime, until: datetime) -> int:
    return max(1, round((until - since).total_seconds() / 86400))


def previous_weekday(now: datetime):
    """The most recent COMPLETE weekday before `now`, as a date.

    Each digest reports one whole working day rather than a rolling 24
    hours, which is what lets Saturday and Sunday be dropped without losing
    a weekday (asked for 2026-09-07):

        Tue-Fri 07:00  ->  reports the previous calendar day
        Mon     07:00  ->  reports FRIDAY, skipping the weekend entirely

    A rolling window could not do this. "Since Friday 07:00" necessarily
    contains the weekend, and clipping it to Monday 00:00 would silently
    drop everything filed after Friday breakfast — a whole working day.
    Whole-day windows make the weekend the only thing that goes missing,
    which is exactly the intent.
    """
    day = now.date() - timedelta(days=1)
    while day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        day -= timedelta(days=1)
    return day


def weekday_window(now: datetime, previous_until=None):
    """(since, until) for this run: one whole weekday, in UTC.

    `previous_until` extends the window backwards when a WEEKDAY was missed —
    a failed Tuesday means Wednesday covers Tuesday and Monday rather than
    mailing Monday to nobody. Such a recovery window can span a weekend, and
    that is the right trade: two quiet days in a catch-up mail cost far less
    than a working day that reached no inbox.

    **The weekend gap is not a missed run**, and getting that wrong was a
    real bug (caught by simulating a week before the first Tuesday ran).
    Monday's digest covers Friday and therefore leaves `covered_until` at
    Saturday 00:00 — which is always earlier than Tuesday's Monday 00:00, so
    a naive `previous_until < since` treated every single Tuesday as a
    recovery and pulled Saturday and Sunday back in. That is precisely the
    weekend the whole design exists to drop, reappearing weekly.

    So the comparison is against the covered_until a HEALTHY predecessor
    would have left — the weekday before this one, plus a day — not against
    this window's own start.
    """
    day = previous_weekday(now)
    until = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    since = datetime.combine(day, time.min, tzinfo=timezone.utc)

    if previous_until is not None:
        healthy_previous = datetime.combine(
            previous_weekday(datetime.combine(day, time.min, tzinfo=timezone.utc))
            + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        if previous_until < healthy_previous:
            since = previous_until
    return since, until


def last_covered_until(conn):
    """Where the previous digest stopped, or None if none ever sent.

    Only a run that actually SENT counts. A failed or skipped run must not
    advance the window, or the changes it never mailed are skipped forever —
    the silent-gap failure step 11 exists to prevent.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT covered_until FROM digest_runs
            WHERE status = 'completed' AND covered_until IS NOT NULL
            ORDER BY covered_until DESC LIMIT 1
            """
        )
        row = cur.fetchone()
    return row[0] if row else None


def create_run_record(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO digest_runs (status) VALUES ('running') RETURNING id")
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def update_run_record(conn, run_id, *, status="completed", covered_since=None,
                      covered_until=None, changes_reported=None, error=None,
                      skipped_reason=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE digest_runs
            SET completed_at = now(), status = %s, covered_since = %s,
                covered_until = %s, changes_reported = %s, error = %s,
                skipped_reason = %s
            WHERE id = %s
            """,
            (status, covered_since, covered_until, changes_reported, error,
             skipped_reason, run_id),
        )
    conn.commit()


def send_email(api_key, to, subject, text, html, sender=DEFAULT_FROM):
    """One POST. Returns Resend's message id.

    The official SDK is deliberately not used. requirements.txt is a pinned
    63-package closure (CLAUDE.md — it was bare names until a deploy resolved
    Python 3.14 against a suite running 3.9), and adding a dependency for a
    single JSON POST would mean re-pinning that whole closure. `requests` is
    already in it, and api/synthesis_agent.py already calls HTTP directly for
    the same reason.
    """
    response = requests.post(
        RESEND_ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"from": sender, "to": [to], "subject": subject,
              "text": text, "html": html},
        timeout=30,
    )
    if response.status_code >= 400:
        # response.text, never the request: the body carries the key.
        raise RuntimeError(
            f"Resend refused the send ({response.status_code}): {response.text[:400]}"
        )
    return response.json().get("id")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="compose and print, send nothing, write no run record",
    )
    args = parser.parse_args()

    api_key = os.environ.get("RESEND_API_KEY")
    recipient = os.environ.get("DIGEST_TO")
    if not args.dry_run and not (api_key and recipient):
        # Named, never echoed. Printing either value here would put a live
        # credential into a CI log, which is a repo file with extra steps.
        missing = [n for n, v in (("RESEND_API_KEY", api_key),
                                  ("DIGEST_TO", recipient)) if not v]
        print(f"  MISSING: {', '.join(missing)} — see .env.local", flush=True)
        sys.exit(1)

    conn = None if args.dry_run else psycopg2.connect(os.environ["DATABASE_URL"])
    run_id = None if args.dry_run else create_run_record(conn)

    now = datetime.now(timezone.utc)
    previous = None if args.dry_run else last_covered_until(conn)
    since, until = weekday_window(now, previous)

    # Already sent. A second run on the same day — a manual dispatch, or
    # GitHub firing a schedule twice — would otherwise mail an identical
    # digest, which is worse than an empty one: the reader cannot tell a
    # duplicate from a day that genuinely repeated itself.
    if previous is not None and previous >= until:
        print(f"  Already covered up to {previous:%Y-%m-%d %H:%M} UTC — "
              "nothing new to report, no mail sent.", flush=True)
        update_run_record(
            conn, run_id, covered_since=since, covered_until=previous,
            changes_reported=0,
            skipped_reason=(
                "duplicate: this window was already sent by an earlier run"
            ),
        )
        conn.close()
        return

    days = window_days(since, until)
    if previous is None:
        print("  No previous digest on file — opening with one weekday.", flush=True)
    elif days > 1:
        print(f"  Catching up: the last digest stopped at "
              f"{previous:%Y-%m-%d %H:%M} UTC, so this covers {days} days.",
              flush=True)

    try:
        response = requests.get(
            f"{API_BASE_URL}/investigate",
            params={"days": days, "as_of": until.isoformat()},
            timeout=60,
        )
        response.raise_for_status()
        mail = compose(response.json(), since, until, app_url=APP_URL)
    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
        detail = describe(exc)
        print(f"  ERROR composing the digest: {detail}", flush=True)
        if conn:
            update_run_record(conn, run_id, status="failed", error=detail)
            conn.close()
        raise

    print(f"  Window: {since:%Y-%m-%d %H:%M} → {until:%Y-%m-%d %H:%M} UTC "
          f"({days} day(s))", flush=True)
    print(f"  Subject: {mail['subject']}", flush=True)
    print(f"  Outcome changes named: {mail['changes_reported']}", flush=True)

    # No empty mail (asked for 2026-09-07). A digest that says "nothing
    # happened" teaches the reader to skim, and then the one that matters is
    # skimmed too — the same argument scripts/check_ops_health.py already
    # makes about a workflow that goes red for things nobody must act on.
    #
    # The window IS advanced on an empty skip, unlike a failure: there was
    # genuinely nothing in it, so re-covering it tomorrow would only find the
    # same nothing. And the run closes as 'completed', because a job that
    # correctly declined to send is a job that worked — GET /ops/status
    # treats zero work as legitimate here for exactly this reason.
    if not mail["has_content"] and not args.dry_run:
        print("  Nothing to report — no mail sent.", flush=True)
        update_run_record(
            conn, run_id, covered_since=since, covered_until=until,
            changes_reported=0,
            skipped_reason=(
                "empty: no trial changed anything in this window, so no "
                "digest was sent"
            ),
        )
        conn.close()
        return

    if args.dry_run:
        print("\n" + "=" * 68 + "\n" + mail["text"], flush=True)
        return

    try:
        message_id = send_email(api_key, recipient, mail["subject"],
                                mail["text"], mail["html"])
    except Exception as exc:  # noqa: BLE001
        detail = describe(exc)
        print(f"  ERROR sending: {detail}", flush=True)
        # The window is NOT advanced on a failure — covered_until stays NULL,
        # so tomorrow's digest re-covers today rather than dropping it.
        update_run_record(conn, run_id, status="failed", error=detail)
        conn.close()
        raise

    update_run_record(
        conn, run_id, covered_since=since, covered_until=until,
        changes_reported=mail["changes_reported"],
    )
    conn.close()
    print(f"Digest sent (Resend id {message_id}).", flush=True)


if __name__ == "__main__":
    main()

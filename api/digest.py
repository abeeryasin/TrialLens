"""Compose the daily digest email (step 12).

Deterministic, per CLAUDE.md sec. 5: every question here has one correct
answer — which changes happened, how many, what the record states about each.
No model is involved, and none should be. Formatting a list of facts is not a
language-understanding problem.

**This module never sends anything and never opens a connection.** It turns
one `/investigate` response into a subject line and two bodies. That split is
deliberate — it means the whole composition is testable for free, with no
network, no database and no Resend account, which is the same free-test-first
rule sec. 7 states for paid model calls. `scripts/send_digest.py` owns the
window, the transport and the run record.

**What leads, and why it is not a balanced summary.** Substantive
primary-outcome changes come first and are named individually; everything
else is a count. Two measured reasons:

  1. It is the finding outside evidence says matters (31.7% prevalence,
     16% effect-size inflation — docs/decisions.md, 2026-09-04) and the only
     one a clinician has actually scored: 9 of 12 worth a researcher's
     attention, 2026-09-07.
  2. It is the only finding at a readable daily volume. Measured over the
     record's first ten days: 65-136 trials change something on a weekday,
     which no one will read, against 0-5 substantive outcome changes, which
     is exactly a morning's worth.

**Vocabulary is sec. 2's, unchanged.** An email is user-visible output and
gets no lighter register than the page: what changed, when it changed
relative to the trial's own milestones, and that it requires review. Never a
verdict, never "eligibility", never an accusation. The subject line is held
to the same rule — it is the part most likely to be read alone.
"""
from datetime import datetime, timedelta
from html import escape

# ClinicalTrials.gov, not TrialLens, for the per-trial link: it is the source
# of every fact in the mail (sec. 4), it needs no login, and it will outlive
# any URL of ours. The TrialLens links below are for the aggregate views,
# which are the things CT.gov cannot show.
CTGOV_STUDY_URL = "https://clinicaltrials.gov/study/{nct_id}"

# One place, because a wrong link in an email cannot be corrected after it is
# sent. Overridable so a staging run does not point at production.
DEFAULT_APP_URL = "https://triallens-frontend.onrender.com"

# Streamlit derives a page's path from its filename, minus the ordering
# prefix and extension: pages/2_Understand.py is served at /Understand.
UNDERSTAND_PATH = "/Understand?nct_id={nct_id}"
INVESTIGATE_PATH = "/Investigate"
MONITOR_PATH = "/Monitor"


def _plural(n, singular, plural_word=None):
    return singular if n == 1 else (plural_word or singular + "s")


def _window_phrase(since: datetime, until: datetime) -> str:
    """Which day this mail covers, named.

    A date, not "the last 24 hours", because the window is one whole weekday
    and Monday's is Friday's. A reader who assumed "since yesterday" would
    look for Sunday's changes and find none — the weekend is dropped on
    purpose, and naming the day is what makes that visible rather than
    puzzling. A catch-up window after a failed run names both ends.
    """
    days = max(round((until - since).total_seconds() / 86400), 1)
    last_day = until - timedelta(days=1)
    if days <= 1:
        return f"{last_day:%A %-d %B}"
    return f"{since:%A %-d %B} to {last_day:%A %-d %B}"


# One trial renaming its drug touched every endpoint it registers and
# produced 12 bullets for what a reader would call one change (NCT06400472,
# real). Capped like every other list in this product, and — the part that
# matters — the remainder is COUNTED in the line that follows, never
# silently dropped. Summarising the twelve into "the drug was renamed" would
# be an interpretation of a study fact, which sec. 2 does not allow here.
CHANGE_LINE_CAP = 6


def describe_outcome_change(change: dict, cap: int = CHANGE_LINE_CAP) -> list:
    """What moved in one outcome change, as a list of plain sentences.

    Every line is the record restated, never interpreted. The measure names
    and window values are the registry's own strings — the same rule the
    page follows, and the reason no direction is computed from a time frame
    (see api/investigate.py's OutcomeWindowChange).
    """
    lines = []
    removed, added = change.get("measures_removed") or [], change.get("measures_added") or []
    for measure in removed:
        lines.append(f"No longer listed: {measure}")
    for measure in added:
        lines.append(f"Now listed: {measure}")
    for moved in change.get("window_changes") or []:
        lines.append(
            f"Observation window moved on “{moved['measure']}”: "
            f"{moved['before']} → {moved['after']}"
        )
    for moved in change.get("description_changes") or []:
        if moved["kind"] == "edited":
            lines.append(
                f"How “{moved['measure']}” is defined changed "
                "(the measure name is unchanged)"
            )
        elif moved["kind"] == "removed":
            lines.append(f"The definition of “{moved['measure']}” was deleted")
        else:
            lines.append(
                f"A definition was filled in for “{moved['measure']}”, "
                "where the entry was previously silent"
            )
    if not lines:
        # Should not happen for a substantive change, but an empty card in an
        # email is worse than an honest one: it reads as a bug, and the
        # reader cannot tell what they are being shown.
        lines.append(
            "The registered primary outcomes changed in a way this summary "
            "could not itemise — open the trial to see the full diff."
        )
    if cap and len(lines) > cap:
        withheld = len(lines) - cap
        lines = lines[:cap] + [
            f"… and {withheld} further {_plural(withheld, 'change')} to this "
            "trial's primary outcomes — open it to read them all"
        ]
    return lines


def subject_line(window: dict, outcomes: dict, since, until) -> str:
    """The part most likely to be read alone, so it carries the finding.

    Never a verdict (sec. 2): "3 primary-outcome changes to review" states
    what is waiting, where "3 trials changed their endpoints after results"
    would be an accusation in a notification bar.
    """
    substantive = outcomes.get("substantive", 0)
    changed = window.get("trials_changed", 0)
    if substantive:
        return (
            f"TrialLens: {substantive} primary-outcome "
            f"{_plural(substantive, 'change')} to review"
        )
    if changed:
        return f"TrialLens: no outcome changes, {changed:,} trials updated"
    return "TrialLens: nothing changed across the watch"


def _count_rows(data: dict) -> list:
    """The findings that travel as numbers, not as cards.

    Each is (label, count, detail). A zero is dropped rather than printed:
    on a page an empty row is a finding, in an eight-line email it is
    filler that pushes the real content down.
    """
    rows = []
    dates = data.get("dates") or []
    pushed = sum(d.get("pushed", 0) for d in dates)
    pulled = sum(d.get("pulled", 0) for d in dates)
    if pushed or pulled:
        rows.append((
            "Timeline moves",
            pushed + pulled,
            f"{pushed} pushed later, {pulled} pulled earlier",
        ))

    lifecycle = data.get("lifecycle") or []
    if lifecycle:
        total = sum(f.get("count", 0) for f in lifecycle)
        anomalies = [f for f in lifecycle if f.get("anomaly")]
        detail = ", ".join(f"{f['count']} {f['label'].lower()}" for f in lifecycle[:3])
        if anomalies:
            detail += f" — {len(anomalies)} flagged as unusual"
        rows.append(("Status changes", total, detail))

    enrollment = data.get("enrollment") or {}
    became = enrollment.get("became_actual_total", 0)
    if became:
        under = enrollment.get("under_target", 0)
        rows.append((
            "Enrolment counts confirmed",
            became,
            f"{under} finished under their stated target" if under
            else "none finished under target",
        ))

    exits = data.get("scope_exits_total", 0)
    if exits:
        rows.append((
            "Left the tracked scope",
            exits,
            "no longer matching a tracked condition — flagged, never deleted",
        ))
    return rows


# The standing caveat. Identical in substance to the Investigate page's, and
# it travels with every mail because an email is read away from the page
# that explains itself.
FOOTER = (
    "A changed endpoint has innocent explanations — a regulator asked, a "
    "typo was fixed, wording was standardised. TrialLens cannot tell which "
    "from the registry alone, so nothing above is a verdict; it says what "
    "changed and when, relative to each trial's own milestones. Every fact "
    "comes from the ClinicalTrials.gov v2 API."
)


def compose(data: dict, since: datetime, until: datetime,
            app_url: str = DEFAULT_APP_URL) -> dict:
    """One /investigate response -> {subject, text, html, changes_reported}.

    `changes_reported` is what the run record stores: the number of things
    this mail actually put in front of a reader, which is the honest measure
    of whether it did any work. It is NOT window.trials_changed — a digest
    that named nothing did no work even if 136 trials moved.
    """
    window = data.get("window") or {}
    outcomes = data.get("outcomes") or {}
    substantive = [
        c for c in (outcomes.get("changes") or [])
        if c.get("category") == "substantive"
    ]
    counts = _count_rows(data)
    covered = _window_phrase(since, until)

    tracked = window.get("trials_tracked", 0)
    changed = window.get("trials_changed", 0)
    headline = (
        f"{changed:,} of {tracked:,} tracked trials were updated on {covered}."
    )

    # ---- plain text ------------------------------------------------------
    # Sent alongside the HTML rather than left for Resend to derive: the
    # text part is what a screen reader, a plain-text client and every
    # search index actually read, and an auto-derived one loses the
    # structure that makes the outcome changes scannable.
    text = ["TrialLens digest", "", headline, ""]

    if substantive:
        shown = len(substantive)
        total = outcomes.get("substantive", shown)
        text.append(
            f"PRIMARY OUTCOME CHANGES REQUIRING REVIEW ({total})"
            + (f" — showing the first {shown}" if shown < total else "")
        )
        text.append("")
        for change in substantive:
            text.append(f"  {change['nct_id']} — {change['brief_title']}")
            for label in change.get("flag_labels") or []:
                text.append(f"    ! {label}")
            for line in describe_outcome_change(change):
                text.append(f"    - {line}")
            text.append(f"    {CTGOV_STUDY_URL.format(nct_id=change['nct_id'])}")
            text.append("")
    else:
        # Zero stated in words, never an omission — the same rule Home's
        # quiet week keeps. An absent section reads as a broken query.
        text += ["No trial changed a registered primary outcome in this window.", ""]

    if outcomes.get("entry_completed") or outcomes.get("reformatting"):
        parts = []
        if outcomes.get("entry_completed"):
            n = outcomes["entry_completed"]
            parts.append(
                f"{n} {_plural(n, 'had', 'had')} a definition filled in "
                "under an unchanged endpoint"
            )
        if outcomes.get("reformatting"):
            n = outcomes["reformatting"]
            parts.append(f"{n} {_plural(n, 'was', 'were')} reformatting only")
        text += ["Also set aside: " + "; ".join(parts) + ".", ""]

    if counts:
        text.append("EVERYTHING ELSE")
        text.append("")
        for label, count, detail in counts:
            text.append(f"  {label}: {count:,} — {detail}")
        text.append("")

    text += [
        f"Open the watch: {app_url}{INVESTIGATE_PATH}",
        f"Every change, one at a time: {app_url}{MONITOR_PATH}",
        "",
        FOOTER,
    ]

    return {
        "subject": subject_line(window, outcomes, since, until),
        "text": "\n".join(text),
        "html": _html(headline, substantive, outcomes, counts, app_url),
        "changes_reported": len(substantive),
        # Whether this mail is worth anyone's inbox (asked for 2026-09-07).
        # Deliberately NOT "no outcome changes": a window with 68 trials
        # updated, 36 timeline moves and 13 status changes has plenty to
        # say, it just has no endpoint change to lead with. Empty means
        # nothing named AND nothing counted AND nothing moved at all.
        "has_content": bool(substantive or counts or changed),
    }


def _html(headline, substantive, outcomes, counts, app_url) -> str:
    """The same content, styled inline.

    Inline styles only, and no external stylesheet or web font: mail clients
    strip <style> blocks and block remote resources, so anything not inline
    is a rule that silently does not apply. Colours are the app's own ink
    and surface tokens rather than a second palette.
    """
    def esc(value):
        return escape(str(value), quote=True)

    ink, muted, rule = "#0b0b0b", "#52514e", "#e6e5e1"
    out = [
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,'
        f'Helvetica,Arial,sans-serif;color:{ink};max-width:640px;'
        'margin:0 auto;padding:24px 20px;line-height:1.5">',
        f'<div style="font-size:13px;color:{muted};letter-spacing:.08em;'
        'text-transform:uppercase">TrialLens digest</div>',
        f'<p style="font-size:16px;margin:12px 0 24px">{esc(headline)}</p>',
    ]

    if substantive:
        total = outcomes.get("substantive", len(substantive))
        heading = f"Primary outcome changes requiring review ({total})"
        if len(substantive) < total:
            heading += f" — showing the first {len(substantive)}"
        out.append(
            f'<h2 style="font-size:15px;margin:0 0 12px;padding-bottom:8px;'
            f'border-bottom:1px solid {rule}">{esc(heading)}</h2>'
        )
        for change in substantive:
            out.append(
                f'<div style="margin:0 0 20px;padding:14px 16px;'
                f'background:#fafaf8;border-radius:6px">'
            )
            out.append(
                f'<div style="font-weight:600;font-size:14px">'
                f'<a href="{esc(CTGOV_STUDY_URL.format(nct_id=change["nct_id"]))}" '
                f'style="color:{ink}">{esc(change["nct_id"])}</a>'
                f' — {esc(change["brief_title"])}</div>'
            )
            for label in change.get("flag_labels") or []:
                out.append(
                    f'<div style="font-size:12px;color:#82071e;margin-top:6px">'
                    f'⚠ {esc(label)}</div>'
                )
            out.append(
                f'<ul style="margin:10px 0 0;padding-left:18px;font-size:14px">'
            )
            for line in describe_outcome_change(change):
                out.append(f"<li>{esc(line)}</li>")
            out.append("</ul>")
            out.append(
                f'<div style="margin-top:10px;font-size:13px">'
                f'<a href="{esc(app_url + UNDERSTAND_PATH.format(nct_id=change["nct_id"]))}" '
                f'style="color:#2a78d6">Read it in TrialLens →</a></div>'
            )
            out.append("</div>")
    else:
        out.append(
            f'<p style="font-size:14px;margin:0 0 20px">No trial changed a '
            "registered primary outcome in this window.</p>"
        )

    if outcomes.get("entry_completed") or outcomes.get("reformatting"):
        parts = []
        if outcomes.get("entry_completed"):
            n = outcomes["entry_completed"]
            parts.append(
                f"{n} {_plural(n, 'had', 'had')} a definition filled in "
                "under an unchanged endpoint"
            )
        if outcomes.get("reformatting"):
            n = outcomes["reformatting"]
            parts.append(f"{n} {_plural(n, 'was', 'were')} reformatting only")
        out.append(
            f'<p style="font-size:13px;color:{muted};margin:0 0 24px">'
            f'Also set aside: {esc("; ".join(parts))}.</p>'
        )

    if counts:
        out.append(
            f'<h2 style="font-size:15px;margin:24px 0 12px;padding-bottom:8px;'
            f'border-bottom:1px solid {rule}">Everything else</h2>'
        )
        out.append('<table style="width:100%;border-collapse:collapse;font-size:14px">')
        for label, count, detail in counts:
            out.append(
                f'<tr><td style="padding:6px 0;vertical-align:top">'
                f'<strong>{esc(label)}</strong><br>'
                f'<span style="color:{muted};font-size:13px">{esc(detail)}</span></td>'
                f'<td style="padding:6px 0;text-align:right;vertical-align:top;'
                f'font-variant-numeric:tabular-nums">{count:,}</td></tr>'
            )
        out.append("</table>")

    out.append(
        f'<p style="margin:28px 0 0;font-size:13px">'
        f'<a href="{esc(app_url + INVESTIGATE_PATH)}" style="color:#2a78d6">'
        "Open the watch</a> &nbsp;·&nbsp; "
        f'<a href="{esc(app_url + MONITOR_PATH)}" style="color:#2a78d6">'
        "Every change, one at a time</a></p>"
    )
    out.append(
        f'<p style="margin:24px 0 0;padding-top:16px;border-top:1px solid {rule};'
        f'font-size:12px;color:{muted}">{esc(FOOTER)}</p>'
    )
    out.append("</div>")
    return "".join(out)

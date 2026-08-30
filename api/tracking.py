"""Why is a trial no longer tracked?

Purely deterministic (CLAUDE.md sec. 5): the answer is computed from two
facts already stored on the record — the trial's own status and its last
ClinicalTrials.gov update date — checked against the exact scope rules
scripts/ingest.py applies (imported from ctgov_client, not restated here,
so this explanation can't drift out of sync with the real fetch).

Deliberately returns None rather than a guess when the stored facts don't
explain the drop: CLAUDE.md sec. 2 forbids inventing a study fact or
presenting an inference as a source fact, and "we can't tell from what we
stored" is a real, honest answer that the UI is expected to show as-is.
"""
from datetime import date, timedelta
from typing import Optional

from ctgov_client import ACTIVE_STATUSES, CLOSED_STATUSES, RECENCY_DAYS

_ACTIVE = set(ACTIVE_STATUSES.split(","))
_CLOSED = set(CLOSED_STATUSES.split(","))

# Two genuinely different kinds of change land in study_changes. Everything
# CT.gov actually reports about a trial is "Trial content"; a column that
# only records TrialLens's own bookkeeping — whether we're still watching
# this trial at all — is "Tracking", and isn't a study fact. Defined here
# rather than in the frontend so there's exactly one definition.
TRACKING_FIELDS = {"active_in_scope"}

CATEGORY_TRIAL_CONTENT = "Trial content"
CATEGORY_TRACKING = "Tracking"


def field_category(field_name: str) -> str:
    return CATEGORY_TRACKING if field_name in TRACKING_FIELDS else CATEGORY_TRIAL_CONTENT

# CT.gov's raw status enums are shouty; these are the same values written
# the way a person would say them.
_STATUS_WORDS = {
    "COMPLETED": "completed",
    "TERMINATED": "terminated",
    "SUSPENDED": "suspended",
    "WITHDRAWN": "withdrawn",
}


def drop_reason(overall_status: Optional[str], last_update_post_date: Optional[date]) -> Optional[str]:
    """A one-line, plain-language reason a trial fell out of tracking, or
    None when the stored data doesn't actually explain it."""
    if not overall_status:
        return None

    if overall_status in _CLOSED:
        if last_update_post_date is None:
            return None
        cutoff = date.today() - timedelta(days=RECENCY_DAYS)
        if last_update_post_date < cutoff:
            months = RECENCY_DAYS // 30
            when = last_update_post_date.strftime("%b %Y")
            return (
                f"This trial is {_STATUS_WORDS.get(overall_status, overall_status.lower())} "
                f"and ClinicalTrials.gov hasn't updated it since {when} — closed trials are "
                f"only tracked for about {months} months after their last update."
            )
        # Closed but still recent: it should still be in scope, so something
        # else dropped it. Don't guess at what.
        return None

    if overall_status not in _ACTIVE:
        return (
            f"This trial's status is now \"{overall_status}\", which isn't one of the "
            "statuses tracked for updates."
        )

    # Still an actively-recruiting status: it ought to have matched. No
    # honest explanation available from what's stored.
    return None

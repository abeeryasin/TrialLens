"""Field-name display labels shared between Understand's per-trial change
history and Monitor's aggregate feed — both render the same study_changes
rows, just at different scopes, so the label/structure mapping is defined
once here instead of copied into each page.
"""
import json
from datetime import datetime, timezone

import streamlit as st

FIELD_LABELS = {
    "brief_title": "Title",
    "official_title": "Official title",
    "overall_status": "Status",
    "study_type": "Study type",
    "phase": "Phase",
    "enrollment_count": "Enrollment",
    "enrollment_type": "Enrollment figure type (target vs. actual)",
    "sex": "Sex",
    "minimum_age": "Minimum age",
    "healthy_volunteers": "Healthy volunteers",
    "eligibility_criteria": "Eligibility criteria",
    "last_update_post_date": "ClinicalTrials.gov's own \"last updated\" date",
    "brief_summary": "Summary",
    "lead_sponsor": "Sponsor",
    "start_date": "Start date",
    "primary_completion_date": "Primary completion date",
    "completion_date": "Completion date",
    "interventions": "Intervention(s)",
    "primary_outcomes": "Primary outcome(s)",
    "locations": "Location(s)",
    # Deliberately a neutral label, not "Active in tracking scope": a field
    # name that asserts "active" reads as contradicting its own "no longer
    # tracked" value. "Tracking status" is parallel to "Status" and asserts
    # nothing on its own.
    "active_in_scope": "Tracking status",
}

# These store a JSON list, not a plain value — render as a formatted
# before/after (Understand) or a placeholder (Monitor's compact table)
# instead of one unreadable inline JSON string.
STRUCTURED_FIELDS = {"interventions", "primary_outcomes", "locations"}

# Two genuinely different kinds of change get written to study_changes:
# "did the trial itself change?" (a real fact ClinicalTrials.gov reports)
# vs. "did OUR tracking of it change?" (TrialLens bookkeeping, not a study
# fact at all). Which field is which is decided API-side (api/tracking.py)
# and comes back on every change row — deliberately not re-listed here, so
# there's one definition rather than two that can drift.
CATEGORY_TRIAL_CONTENT = "Trial content"
CATEGORY_TRACKING = "Tracking"

# CT.gov's enrollmentInfo.type. Without this, "Enrollment: 34" is genuinely
# ambiguous — 34 people actually enrolled, or 34 the sponsor hopes to
# recruit? Most records are the latter.
ENROLLMENT_TYPE_CAPTIONS = {
    "ACTUAL": "Actual number enrolled, as reported to ClinicalTrials.gov.",
    "ESTIMATED": "The sponsor's target — not a count of people actually enrolled.",
}


# A raw "true"/"false" string means nothing on its own — active_in_scope
# specifically means "still being tracked", not a generic yes/no, so it
# gets its own real-world phrasing. Any other boolean field falls back to
# a plain Yes/No.
BOOLEAN_LABELS_BY_FIELD = {
    "active_in_scope": {"true": "Tracked", "false": "No longer tracked"},
}


def humanize_value(field_name, raw_value):
    """Turn a raw stored value into something a person would actually
    say — mainly targets the literal "true"/"false" strings study_changes
    stores for boolean fields (see docs/decisions.md, 2026-08-29)."""
    if raw_value is None:
        return "—"
    lowered = str(raw_value).lower()
    field_map = BOOLEAN_LABELS_BY_FIELD.get(field_name)
    if field_map and lowered in field_map:
        return field_map[lowered]
    if lowered in ("true", "false"):
        return "Yes" if lowered == "true" else "No"
    return raw_value


def format_detected_at(raw_value):
    """A raw ISO timestamp ("2026-08-29T00:02:06.604034Z") is precise but
    unreadable — shows a human date/time plus a relative "how long ago"
    alongside it, per UX Movement / Cloudscape guidance on timestamp
    display (docs/decisions.md, 2026-08-29)."""
    if not raw_value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return raw_value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    if seconds < 60:
        relative = "just now"
    elif seconds < 3600:
        relative = f"{int(seconds // 60)}m ago"
    elif seconds < 86400:
        relative = f"{int(seconds // 3600)}h ago"
    elif seconds < 2592000:
        relative = f"{int(seconds // 86400)}d ago"
    else:
        relative = f"{int(seconds // 2592000)}mo ago"

    absolute = dt.strftime("%b %d, %Y, %I:%M %p UTC")
    return f"{absolute} ({relative})"


def render_structured_diff(old_value, new_value):
    """Real before/after columns for a structured (JSON) field change —
    used by both Understand's per-trial history and Monitor's aggregate
    feed, so the two never render this differently."""
    old_col, new_col = st.columns(2)
    for col, heading, raw_value in ((old_col, "Before", old_value), (new_col, "After", new_value)):
        col.caption(heading)
        if not raw_value:
            col.write("—")
            continue
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError):
            col.write(raw_value)
        else:
            col.json(parsed)

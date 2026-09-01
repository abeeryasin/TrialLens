"""Field-name display labels shared between Understand's per-trial change
history and Monitor's aggregate feed — both render the same study_changes
rows, just at different scopes, so the label/structure mapping is defined
once here instead of copied into each page.
"""
import difflib
import html
import json
import re
from datetime import date, datetime, timezone

import streamlit as st

FIELD_LABELS = {
    "brief_title": "Title",
    "official_title": "Official title",
    "overall_status": "Status",
    "study_type": "Study type",
    "phase": "Phase",
    "enrollment_count": "Enrollment",
    "enrollment_type": "Enrollment figure type (target vs. actual)",
    "has_results": "Posted results",
    "sex": "Sex",
    "minimum_age": "Minimum age",
    "maximum_age": "Maximum age",
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


# Headings for the aspect groups inside an amendment (api/amendments.py).
# Each says what the group means rather than just naming it — "Scientific"
# alone doesn't tell a reader why those rows are first.
ASPECT_CAPTIONS = {
    "Scientific": "🔬 **Scientific** — what the trial studies, and in whom",
    "Operational": "⚙️ **Operational** — how it's running: status, numbers, dates, sites",
    "Administrative": "📝 **Administrative** — how the record describes itself",
    "Uncategorised": "**Uncategorised** — a field TrialLens hasn't classified yet",
}


def format_posted_on(raw_value):
    """A date ClinicalTrials.gov stamped on a record version ("2026-08-31").

    Date only, and no relative "3d ago": this is the registry's own version
    stamp, a fact about the trial. format_detected_at above is for OUR
    timestamps — when the cron happened to look — and the two must not read
    alike, because confusing "the sponsor amended this" with "we noticed
    this" attributes our scheduling to the trial.
    """
    if not raw_value:
        return "—"
    try:
        return date.fromisoformat(str(raw_value)).strftime("%d %B %Y")
    except ValueError:
        return str(raw_value)


def format_posted_on_list(raw_values):
    """One or more CT.gov version dates as a readable series.

    "28 August 2026" · "28 and 31 August 2026" · "28 August, 1 September 2026"

    The year is stated once when they share it: repeating it three times in
    one sentence is noise, and no trial has more than three of these (the
    real maximum, measured 2026-09-02 — 79 of 88 have exactly one).
    """
    parsed = []
    for value in raw_values:
        try:
            parsed.append(date.fromisoformat(str(value)))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return ""
    parsed.sort()

    def join(parts):
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]

    same_year = len({d.year for d in parsed}) == 1
    same_month = same_year and len({d.month for d in parsed}) == 1

    if same_month:
        # "28 and 31 August 2026" — repeating the month between two days a
        # few apart is how a form writes a date, not how a person does.
        days = join([d.strftime("%d").lstrip("0") for d in parsed])
        return f"{days} {parsed[0].strftime('%B')} {parsed[0].year}"
    if same_year:
        return join([d.strftime("%d %B").lstrip("0") for d in parsed]) + f" {parsed[0].year}"
    return join([d.strftime("%d %B %Y").lstrip("0") for d in parsed])


def format_recording_since(raw_value):
    """When TrialLens began recording changes at all — a date, not a
    timestamp, because the claim it supports ("watching since X") is only
    ever true to the day."""
    if not raw_value:
        return "we began tracking"
    try:
        dt = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return str(raw_value)
    return dt.strftime("%d %B %Y")


# Above this many characters, showing both full versions side by side stops
# being readable — a real eligibility_criteria change is ~4,000 characters
# per side, and dumping both to communicate a handful of edited words is
# what this threshold exists to avoid.
LONG_TEXT_CHARS = 200


def format_age_range(minimum_age, maximum_age):
    """A trial's real age bracket. CT.gov reports each bound with its unit
    attached and the unit genuinely varies ("18 Years", "18 Months"), so
    these are shown as-is rather than parsed into numbers — about half of
    trials specify no upper bound at all, which is a real fact about the
    trial, not missing data."""
    if minimum_age and maximum_age:
        return f"{minimum_age} to {maximum_age}"
    if minimum_age:
        return f"{minimum_age} and older"
    if maximum_age:
        return f"Up to {maximum_age}"
    return "—"


def is_long_text(old_value, new_value):
    return max(len(old_value or ""), len(new_value or "")) > LONG_TEXT_CHARS


def _words(text):
    """Split keeping punctuation attached, so a diff reports real words
    rather than stray symbols."""
    return (text or "").split()


def is_formatting_only(old_value, new_value):
    """True when the two versions differ ONLY in punctuation, casing, or
    whitespace — e.g. a sponsor reformatting a run-on list into bullets.
    Deterministic string comparison, never a judgement call: the texts are
    normalized identically and compared exactly.

    Deliberately biased toward saying "no": only non-alphanumeric
    differences are ignored, so anything that touches a number or a word
    is a real change. Missing a genuinely cosmetic edit is harmless; the
    opposite — telling a researcher nothing changed when a BMI cutoff
    moved 35 -> 45, or an "eGFR < 60" became "< 30", or a "no" was dropped
    — would be a false claim about a study fact (CLAUDE.md sec. 2). All
    four of those cases were checked and correctly return False."""
    def normalize(text):
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()

    if old_value is None or new_value is None:
        return False
    return old_value != new_value and normalize(old_value) == normalize(new_value)


def summarize_text_change(old_value, new_value):
    """A short, honest cell label for a long text change — never a
    paraphrase of the clinical text itself, just a count of what moved."""
    if is_formatting_only(old_value, new_value):
        return "Reformatted only — same wording"
    matcher = difflib.SequenceMatcher(None, _words(old_value), _words(new_value))
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return f"Text changed (+{added} / −{removed} words)"


def render_text_diff(old_value, new_value):
    """Inline word-level diff: one readable passage with removals struck
    through and additions highlighted, rather than two near-identical walls
    of text. Uses difflib (the same approach git diff takes) — the exact
    words that changed, never an LLM's summary of them, which would risk
    paraphrasing clinical criteria (CLAUDE.md sec. 2)."""
    if is_formatting_only(old_value, new_value):
        st.success(
            "Formatting only — punctuation, capitalisation or layout changed, "
            "but the wording is identical. No change to what the trial requires."
        )

    matcher = difflib.SequenceMatcher(None, _words(old_value), _words(new_value))
    old_words, new_words = _words(old_value), _words(new_value)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(html.escape(" ".join(old_words[i1:i2])))
            continue
        if tag in ("replace", "delete"):
            removed = html.escape(" ".join(old_words[i1:i2]))
            parts.append(
                f'<span style="background:#ffd7d5;color:#82071e;'
                f'text-decoration:line-through">{removed}</span>'
            )
        if tag in ("replace", "insert"):
            added = html.escape(" ".join(new_words[j1:j2]))
            parts.append(f'<span style="background:#ccffd8;color:#0a3622">{added}</span>')

    st.markdown(
        '<div style="line-height:1.7;white-space:pre-wrap">' + " ".join(parts) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Struck-through red = removed · green = added · plain = unchanged")


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

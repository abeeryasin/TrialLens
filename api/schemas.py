"""Pydantic models: FastAPI's input validation and response typing.

A Pydantic model isn't just documentation — FastAPI actually checks
incoming JSON against it before your route code runs (wrong type, missing
required field -> 422 response, route code never executes), and uses it
to build the response JSON on the way out.

Uses typing.Optional/List/Dict rather than the `X | None` syntax: this
project's venv is Python 3.9, and Pydantic evaluates annotations at
runtime, which the newer union syntax doesn't support there.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Intervention(BaseModel):
    """What's actually being done to participants — a drug, device, or
    procedure. The single most-requested field after title/condition in a
    real study of what researchers find helpful in a results list (see
    docs/decisions.md, 2026-08-29)."""

    type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class OutcomeMeasure(BaseModel):
    """What defines success for the trial — e.g. "Alpha diversity of the
    periodontal microbiota using Chao-1 index" (a real primary outcome,
    not an abstraction)."""

    measure: Optional[str] = None
    description: Optional[str] = None
    time_frame: Optional[str] = None


class TrialLocation(BaseModel):
    facility: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class StudySummary(BaseModel):
    """One row in a GET /studies list — enough to identify and triage a trial."""

    nct_id: str
    brief_title: str
    overall_status: str
    phase: Optional[str] = None
    last_update_post_date: date
    active_in_scope: bool


class StudyDetail(StudySummary):
    """Everything for GET /studies/{nct_id} — full normalized record + conditions."""

    official_title: Optional[str] = None
    study_type: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL vs ESTIMATED — see ctgov_client.py
    has_results: Optional[bool] = None  # CT.gov has posted results for this trial
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    maximum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    fetched_at: datetime
    last_matched_at: datetime
    conditions: List[str] = []
    brief_summary: Optional[str] = None
    lead_sponsor: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    interventions: List[Intervention] = []
    primary_outcomes: List[OutcomeMeasure] = []
    locations: List[TrialLocation] = []


# Every column a StudyDetail (or TrialDetail — same DB-backed field set)
# needs, and nothing else. Use this instead of `SELECT *`.
#
# `SELECT *` also fetches raw_json, the untouched CT.gov response. Nothing
# reads it — Pydantic silently drops the extra key — but it is 8.7 KB per
# row and 95 MB of the table's 137 MB (measured 2026-08-31, 11,469 active
# trials), so every full-table read spent 69% of its bytes on a column that
# was thrown away on arrival. That is billable egress on Neon's free tier,
# which is 5 GB/month; see docs/decisions.md.
#
# Derived from the model rather than typed out, so a new field can't drift
# out of sync with the query that has to fetch it.
STUDY_DETAIL_COLUMNS = ", ".join(
    name for name in StudyDetail.model_fields if name != "conditions"
)


class StudyList(BaseModel):
    total: int
    limit: int
    offset: int
    results: List[StudySummary]


class StudyUpsert(BaseModel):
    """One study as written by ingest.py, matching extract_fields() in ctgov_client.py."""

    nct_id: str
    brief_title: str
    official_title: Optional[str] = None
    overall_status: str
    study_type: Optional[str] = None
    phase: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL vs ESTIMATED — see ctgov_client.py
    has_results: Optional[bool] = None  # CT.gov has posted results for this trial
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    maximum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    last_update_post_date: date
    conditions: List[str] = []
    raw_json: Dict[str, Any]
    brief_summary: Optional[str] = None
    lead_sponsor: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    interventions: List[Intervention] = []
    primary_outcomes: List[OutcomeMeasure] = []
    locations: List[TrialLocation] = []


class BatchUpsertResult(BaseModel):
    studies_written: int
    condition_tags_written: int
    changes_detected: int


class StudyChange(BaseModel):
    """One detected field-level change — the real Monitor changelog entry."""

    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    detected_at: datetime
    # "Trial content" or "Tracking" — see api/tracking.py. Set by the route,
    # not stored; it's a property of the field, not of the row.
    category: Optional[str] = None


class StudyChangeList(BaseModel):
    nct_id: str
    changes: List[StudyChange]


class AmendedField(StudyChange):
    """One field that moved inside an amendment, with what code can say
    about it — never what a model thinks it means."""

    aspect: Optional[str] = None
    # "Scientific" | "Operational" | "Administrative", from api/amendments.py.
    # None means the field is not yet classified, and the UI shows it as
    # uncategorised rather than filing it under the least alarming bucket.

    effect: Optional[str] = None
    # A plain-language, arithmetic-only effect: "pushed about 12 months
    # later", "6 sites added", "the recruitment target was replaced by a
    # real enrolled count". None whenever no honest computation exists —
    # which is always the case for prose fields, where saying what a
    # rewrite MEANS would be a reading of clinical text, not a calculation.

    interpretation: Optional[str] = None
    # A MODEL's reading of a prose diff (step 7c), stored in
    # study_changes.prose_interpretation and written by claude-haiku-4-5 —
    # the one thing on this object that is not computed from the two values
    # beside it. It exists precisely where `effect` cannot: an eligibility
    # rewrite has no arithmetic.
    #
    # It is NOT a study fact and any UI showing it MUST attribute it, must
    # show the real diff alongside rather than instead, and must never merge
    # it into the same visual register as `effect` (CLAUDE.md sec. 2 and 3).
    #
    # None carries THREE different meanings that the stored column cannot
    # tell apart: the field is not a prose field, the change predates
    # 2026-09-03 when interpretation began, or the model was asked and
    # answered MEANINGFUL: no. So absence is never evidence that nothing
    # important changed, and the page must not imply it is.


class Amendment(BaseModel):
    """One amendment ClinicalTrials.gov posted to a trial, and what moved.

    Dated by the registry's own version stamp (`posted_on`), not by when
    TrialLens noticed. Those differ — the cron runs every 6 hours, and a
    trial first seen after a long gap can carry a stamp weeks older than
    our detection. The registry's date is the fact about the trial; ours is
    a fact about our scheduler.
    """

    posted_on: date
    # CT.gov's last_update_post_date AFTER this amendment.

    previously_posted_on: Optional[date] = None
    # ...and before it. Together these say "this record went from the
    # version posted on X to the version posted on Y".

    detected_at: datetime
    # When TrialLens saw it. Always >= posted_on, often by hours or more.

    changes: List[AmendedField] = []
    # The trial-content fields that moved in this amendment. Empty is a
    # real and common answer — see content_is_visible.

    aspects: List[str] = []
    # Which aspects this amendment touched ("Scientific", "Operational",
    # "Administrative"), most consequential first. Lets a reader see that a
    # primary outcome was rewritten without reading every row.

    content_is_visible: bool = True
    # False when CT.gov posted an amendment but every field it touched is
    # one TrialLens does not store (47% of amendments, measured 2026-09-01).
    # The UI MUST render this as "amended, but we can't see what" and never
    # as "no changes" — the latter is a false claim about a study fact
    # (CLAUDE.md sec. 2). Absence of visible changes is not absence of
    # change.


class AmendmentHistory(BaseModel):
    """A trial's amendments, newest first — the thing ClinicalTrials.gov
    structurally cannot show, because it holds only the current version."""

    nct_id: str
    amendments: List[Amendment] = []
    total_amendments: int = 0

    invisible_amendment_count: int = 0
    # How many of the above touched only untracked fields. Surfaced as a
    # number so the page can be honest about its own blind spot rather than
    # leaving the reader to count flagged rows.

    recording_since: Optional[datetime] = None
    # When TrialLens began recording changes AT ALL — the earliest
    # detected_at in the whole table, not this trial's own start date.
    # Deliberately a global fact: no per-trial "first observed" column
    # exists, so claiming this trial was watched from that date would
    # overstate what is known about it (sec. 2). Every count here means
    # "since we started watching", never "since the trial was registered":
    # a trial amended eleven times before this date shows none of them.

    unattributed_changes: List[StudyChange] = []
    # Content changes belonging to no amendment. Should always be empty:
    # every content change is written in the same transaction as the
    # last_update_post_date change that explains it, so they share an exact
    # detected_at (0 exceptions in 195 changes, measured 2026-09-01).
    # Returned rather than dropped because if that ever stops being true,
    # silently discarding real recorded changes would be the worst possible
    # failure — a trial would look quieter than it was.


class WatchDay(BaseModel):
    """One day on the watch's 7-day record, including the empty ones.

    A zero here is a finding, not missing data: "we checked and nothing was
    amended" is a different statement from "we have no record of that day",
    and the day rows are generated from a date series rather than from the
    changes themselves specifically so a quiet day still appears.
    """

    day: date
    amendments: int


class WatchAmendment(BaseModel):
    """The most recent amendment across every watched trial — the "last
    thing that happened" card, so the screen is never blank.

    Same shape as one Amendment from a trial's history, plus the trial it
    belongs to, since this one spans all of them.
    """

    nct_id: str
    brief_title: str
    posted_on: date
    previously_posted_on: Optional[date] = None
    detected_at: datetime
    changes: List[AmendedField] = []
    aspects: List[str] = []
    content_is_visible: bool = True


class WatchRecent(BaseModel):
    """The last 24 hours, counted by what it MEANS rather than by rows.

    "63 amendments" is a row count, and a row count is exactly the kind of
    number the removed ranking layer was good at and useless for. "One trial
    published its results, three others changed something scientific" is the
    same 63 rows read as a finding. Both are here: the headline needs the
    finding, the honesty needs the total.
    """

    window_hours: int
    amendments: int
    trials: int
    scientific: int
    # Amendments touching at least one field api/amendments.py classifies as
    # Scientific — what the trial studies, and in whom.
    results_posted: int
    # Amendments where has_results went false -> true. A SUBSET of
    # scientific, not a separate bucket: the UI subtracts when it says
    # "N others". The single most consequential amendment a trial carries,
    # and one TrialLens could not see at all before 2026-09-02.


class WatchStatus(BaseModel):
    """Everything the front page states about the watch itself.

    One endpoint rather than five, because these numbers are read together
    and only make sense together — "11,427 watched" is a different claim
    depending on whether the last check was 2 hours or 3 days ago.
    """

    trials_watched: int
    conditions: List[str]

    # ---- Is the watch alive? ----
    last_checked_at: Optional[datetime] = None
    # Read from monitor_runs table (step 7b direction 3, 2026-09-02).
    # Records the completion time of the most recent scheduled run.
    hours_since_check: Optional[float] = None
    check_interval_hours: int
    checks_missed: int = 0
    # Derived from elapsed time and the cron interval, not from a run log:
    # how many scheduled checks should have happened since the last one we
    # can see evidence of. 0 while healthy.

    is_healthy: bool
    # False means SHOW THE ALARM INSTEAD OF THE PAGE, not a banner above a
    # normal-looking feed — a stale feed under a small warning still reads
    # as current, which is the failure being designed out (design/README.md).

    # ---- What has been happening ----
    daily: List[WatchDay] = []
    recent: WatchRecent
    hours_since_last_amendment: Optional[float] = None
    last_amendment: Optional[WatchAmendment] = None

    # ---- Something to do on a quiet day ----
    trials_with_results: int
    completed_with_results: int

    # ---- The record: what a fresh clone does not have ----
    recording_since: Optional[datetime] = None
    changes_recorded: int
    amendments_seen: int


class ChangeFeedEntry(StudyChange):
    """One row in the aggregate Monitor feed (GET /changes) — same shape as
    StudyChange plus which trial it belongs to, since the feed spans every
    tracked trial, not one nct_id."""

    nct_id: str
    brief_title: str
    # Only set on a "no longer tracked" change, and only when the stored
    # data actually explains it — None means "we can't tell", which the UI
    # shows honestly rather than filling in (see api/tracking.py).
    tracking_note: Optional[str] = None


class ChangedField(BaseModel):
    """One filterable field on the Monitor feed, with which kind of change
    it represents (see api/tracking.py)."""

    name: str
    category: str


class ChangeFeedResponse(BaseModel):
    total: int
    distinct_trials: int
    limit: int
    offset: int
    results: List[ChangeFeedEntry]


class ReconcileScopeRequest(BaseModel):
    """Sent once per condition at the end of an ingest run: the full set of
    nct_ids this run's cheap-filter fetch actually matched, so anything
    previously tracked under this condition but not in that set gets
    flagged (never deleted), and everything still in it gets confirmed."""

    condition: str
    current_nct_ids: List[str]


class ReconcileScopeResult(BaseModel):
    confirmed_in_scope: int
    dropped_out_of_scope: int


class KnownDatesRequest(BaseModel):
    """Cheap-filter support: which last_update_post_date do we already have
    stored for these nct_ids? Missing keys in the response mean "never seen
    before" — always worth the expensive re-fetch."""

    nct_ids: List[str]


class KnownDatesResponse(BaseModel):
    known_dates: Dict[str, date]


class DiscoverResult(BaseModel):
    """One trial in a GET /discover response, tagged with where it actually
    came from — "tracked" (already in our DB, kept fresh by Monitor) or
    "live" (fetched from CT.gov for this request only, not stored). Lives
    on each result, not the response, because a response can mix both: an
    untracked condition's local rows are only ever incidental, never proof
    of a complete picture on their own."""

    nct_id: str
    brief_title: str
    overall_status: str
    phase: Optional[str] = None
    last_update_post_date: Optional[date] = None
    source: str  # "tracked" or "live"


class DiscoverResponse(BaseModel):
    condition: str
    total: int
    results: List[DiscoverResult]
    note: str


class ExplorePlace(BaseModel):
    """One country, or one city within a country, that a trial runs in.

    A rollup exists because a site LIST is unusable at the top end: the
    median trial has 1 site but the largest has 1,568 across 899 cities
    (measured 2026-09-04). Grouping is also what defers the merge —
    "who else works in this space?" is a question about places, and 381
    spellings of one Madrid hospital collapse to one city either way.

    The three status counts are separate rather than a recruiting/not
    boolean because 71.4% of live site edges carry no stated status, and
    folding those in with the closed ones would report silence as closure
    (docs/plan_explore_nodes.md sec. 4b).
    """

    country: Optional[str] = None
    city: Optional[str] = None  # None on a country-level row
    sites: int
    recruiting: int
    other_stated: int
    # Stated, but something other than RECRUITING — which is NOT the same as
    # closed: NOT_YET_RECRUITING lives here too. The exact code is on each
    # ExploreSite; this bucket only means "the registry said something".
    not_stated: int


class ExploreSite(BaseModel):
    """One place a trial runs, as the registry reported it.

    `facility` is the raw source string, unmerged (db/schema.sql). It is
    here rather than only in the rollup because the documented clinician
    workflow ends in a phone call to a named hospital, and a city name
    cannot be phoned.
    """

    facility: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    status: Optional[str] = None
    # CT.gov's per-location recruitment status, raw. None means the registry
    # did not state one — never "not recruiting". Rendered through
    # frontend/labels.format_site_status, which is the one place that
    # sentence is written.
    placeable: bool = True
    # False when the site has no coordinates and so cannot go on a map.
    # 1,659 sites (3,705 live edges) are in this state, and a map that
    # dropped them silently would under-report exactly the way step 4 did.
    delisted_at: Optional[datetime] = None
    # Set only on ExploreSites.delisted — the trial's record stopped listing
    # this location, and this is when a backfill first could not find it.
    # NOT the date the trial made the change; nothing on file says that.


class ExploreSites(BaseModel):
    """Where a trial runs, at three zoom levels plus what we cannot show."""

    total: int
    recruiting: int
    other_stated: int
    not_stated: int
    unplaceable: int

    countries: List[ExplorePlace] = []
    cities: List[ExplorePlace] = []
    cities_total: int = 0
    # How many distinct cities exist, against however many `cities` holds.
    # The page states both, so a capped list never reads as a complete one.

    listed: List[ExploreSite] = []
    listed_truncated: bool = False
    # True when `listed` is a capped sample of `total` rather than all of
    # it. The page MUST say so — "12 sites" printed above a list of 50 rows
    # drawn from 1,568 is a false claim about the trial.

    delisted: int = 0
    delisted_sites: List[ExploreSite] = []
    # Locations the trial dropped since TrialLens started watching. Rare (41
    # edges across 23 trials, 2026-09-04) and deliberately kept rather than
    # deleted — "this trial quietly dropped three sites" is a finding in a
    # watch-over-time product, not an inconsistency to clean away.


class ExploreOrganization(BaseModel):
    """A sponsor or collaborator on this trial.

    `role` carries which one, because they share a table on purpose: 887
    names are both, and splitting them would make one organization two
    nodes. Collaborator is deliberately NOT a network to traverse — the
    registry's own definition merges funders with co-designers and excludes
    individuals — so it renders as an attribute of this trial
    (docs/plan_explore_nodes.md sec. 1).
    """

    name: str
    role: str  # 'LEAD' | 'COLLABORATOR'
    org_class: Optional[str] = None  # INDUSTRY / NIH / OTHER_GOV / ...
    other_trials: int = 0
    # Tracked trials this organization appears on, excluding this one. The
    # first genuinely two-hop number on the page: trial -> org -> trials.
    delisted_at: Optional[datetime] = None


class ExploreInvestigator(BaseModel):
    """A named official on this trial.

    The only node type that can answer the people-shaped reading of "who
    else works in this space", since the collaborator field bans
    individuals outright. Mostly real people — 5,325 of 7,722 names carry
    an MD or PhD and only 76 look like a contact desk — but the desks are
    exactly the high-degree ones (a pharma call centre sits on 102 trials,
    a professor on three), which is why nothing here ranks investigators by
    trial count.
    """

    name: str
    affiliation: Optional[str] = None
    role: str  # PRINCIPAL_INVESTIGATOR | STUDY_DIRECTOR | STUDY_CHAIR
    other_trials: int = 0
    delisted_at: Optional[datetime] = None


class ExploreIntervention(BaseModel):
    """One intervention term as the registry received it.

    "term", not "drug": these are surface forms, unmerged, so 55 spellings
    of semaglutide are 55 terms. `other_trials` therefore undercounts a
    real drug's reach, and the page must not present it as a drug's
    landscape.
    """

    name: str
    type: str
    other_trials: int = 0
    delisted_at: Optional[datetime] = None


class ExploreNeighbour(BaseModel):
    """Another tracked trial reachable in two hops, and the evidence for it.

    `conditions` carries the neighbour's own condition tags rather than a
    count of how many it shares with the anchor trial, and that is a
    deliberate correction made 2026-09-04. The count was written first and
    was actively misleading: RxPONDER and its nearest neighbour share 1,047
    sites and, by exact string match, ZERO conditions — while both are
    breast cancer trials. One tags morphology ("Invasive Breast Carcinoma"),
    the other AJCC stage ("Stage IIB Breast Cancer AJCC v6 and v7"). Nothing
    is merged, so "0 in common" measured spelling, not subject matter, and
    printing it under two breast cancer trials would have been a false
    claim dressed as arithmetic (CLAUDE.md sec. 2).

    Showing the tags themselves is the same rule sec. 3 applies everywhere
    else: the source text and the interpretation, never the conclusion
    alone. The researcher reads "Recurrent Breast Carcinoma" and knows in
    one glance what a number could not tell them.
    """

    nct_id: str
    brief_title: str
    overall_status: str
    shared: int
    # How many sites / investigators / terms this trial has in common with
    # the anchor. A plain count of source facts, never a similarity score —
    # /rank was measured and deleted for putting unexplainable numbers on
    # screen (docs/roadmap.md, step 7).
    shared_names: List[str] = []
    # WHICH ones, where naming them is possible. Empty for sites, because
    # the real answer runs to 1,047 facility strings; the count and the
    # conditions carry the evidence there instead.
    conditions: List[str] = []


class ExploreNeighbours(BaseModel):
    """Trials reachable from this one, kept in three separate lists.

    Never fused into a single ranked "related trials" list. Sharing a
    hospital and sharing a principal investigator are different claims with
    different strengths, and blending them into one number would rebuild
    exactly the black-box ranking this project removed. Three lists, three
    stated reasons, and the reader decides which reason they care about.
    """

    by_site: List[ExploreNeighbour] = []
    by_site_total: int = 0
    by_investigator: List[ExploreNeighbour] = []
    by_investigator_total: int = 0
    by_intervention: List[ExploreNeighbour] = []
    by_intervention_total: int = 0
    # Each list is capped; each total is the real number of trials reachable
    # that way. A mega-trial reaches 1,497 others through shared sites, and
    # showing ten of them without the denominator would read as "this trial
    # has ten neighbours".


class ExploreResponse(BaseModel):
    """Everything Explore states about one trial's relationships.

    One endpoint for one screen, the same shape /watch takes: these
    numbers are read together and a site count means something different
    depending on how many of them the registry gave a status for.
    """

    nct_id: str
    brief_title: str
    overall_status: str
    conditions: List[str] = []
    sites: ExploreSites
    organizations: List[ExploreOrganization] = []
    investigators: List[ExploreInvestigator] = []
    interventions: List[ExploreIntervention] = []
    neighbours: ExploreNeighbours = ExploreNeighbours()


class TrialDetail(BaseModel):
    """Full detail for one trial, tracked or not — Understand's real
    response shape. The tracked-only fields (fetched_at, last_matched_at,
    active_in_scope) are None for a live result, since those concepts —
    "when did we last fetch/confirm this" — don't apply to a trial we
    don't actually store."""

    nct_id: str
    brief_title: str
    official_title: Optional[str] = None
    overall_status: str
    study_type: Optional[str] = None
    phase: Optional[str] = None
    enrollment_count: Optional[int] = None
    enrollment_type: Optional[str] = None  # ACTUAL vs ESTIMATED — see ctgov_client.py
    has_results: Optional[bool] = None  # CT.gov has posted results for this trial
    sex: Optional[str] = None
    minimum_age: Optional[str] = None
    maximum_age: Optional[str] = None
    healthy_volunteers: Optional[bool] = None
    eligibility_criteria: Optional[str] = None
    last_update_post_date: Optional[date] = None
    conditions: List[str] = []
    source: str  # "tracked" or "live"
    fetched_at: Optional[datetime] = None
    last_matched_at: Optional[datetime] = None
    active_in_scope: Optional[bool] = None
    # Why this trial is no longer tracked, when the stored data explains it
    # — None (shown honestly as "we can't tell") otherwise. See api/tracking.py.
    tracking_note: Optional[str] = None
    brief_summary: Optional[str] = None
    lead_sponsor: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    interventions: List[Intervention] = []
    primary_outcomes: List[OutcomeMeasure] = []
    locations: List[TrialLocation] = []


# ============================================================================
# Investigate — cross-trial synthesis (step 9)
# ============================================================================
#
# Every model here carries a total alongside whatever list it names, and a
# count of what could not be read. That is the same rule Explore's capped
# lists keep, applied to an aggregate: a finding without its denominator is
# a claim about the corpus that nobody can check.


class TrialRef(BaseModel):
    nct_id: str
    brief_title: str


class DateMove(TrialRef):
    """One trial's date change, with the arithmetic already done."""

    field_name: str
    old_value: str
    new_value: str
    delta_days: int  # signed: positive is later
    # At least one side was month-precision ("2027-06"). ~23% of CT.gov
    # dates are, and the flag has to travel with the number — a reader
    # told "slipped 184 days" about a value the registry gave to the
    # month has been given precision that does not exist (sec. 2).
    imprecise: bool
    effect: str  # the same sentence Understand shows for this row
    detected_at: datetime


class DateMovement(BaseModel):
    """What happened to one date field across the whole window."""

    field_name: str
    label: str
    pushed: int  # got later
    pulled: int  # got earlier
    median_push_days: Optional[int] = None
    median_pull_days: Optional[int] = None
    # Real moves where at least one side was month-precision. If this is a
    # large share of `pushed + pulled`, the medians above are approximate
    # and the page must say so rather than printing a bare day count.
    imprecise_moves: int = 0
    # Rows that changed but did not move the date: a month-precision value
    # gaining a day ("2026-03" -> "2026-03-15") is an artefact of anchoring
    # both sides to the 1st, not a 15-day slip.
    precision_only: int = 0
    no_move: int = 0
    # Counted, never dropped (rule 2). A parse failure that silently
    # vanished would shrink the denominator and overstate everything else.
    unreadable: int = 0
    rows_seen: int
    biggest: List[DateMove] = []
    biggest_total: int = 0


class StatusMove(TrialRef):
    old_value: str
    new_value: str
    detected_at: datetime


class LifecycleFinding(BaseModel):
    """Status transitions that mean the same thing, counted together."""

    kind: str
    label: str
    count: int
    # Anomalies sort first regardless of count and are flagged for the UI.
    # COMPLETED -> RECRUITING happened once in the first eight days; a
    # synthesis that averages away the one surprising row in the record has
    # failed at the only job it has.
    anomaly: bool = False
    trials: List[StatusMove] = []


class EnrollmentMove(TrialRef):
    """A trial's enrollment target meeting reality, or being revised.

    `old_type`/`new_type` are None for a plain count revision — nothing
    switched, the plan just changed. `count_moved` False means the type
    switched while the number stayed put: the trial enrolled exactly its
    target, which is a statement the record makes and not a missing value.
    """

    old_type: Optional[str] = None
    new_type: Optional[str] = None
    count_before: Optional[int] = None
    count_after: Optional[int] = None
    count_moved: bool = False
    # True when the count did not move in this amendment but DID move in a
    # later one, so today's stored figure cannot honestly be attributed
    # here. count_before/count_after are None in that case, and the page
    # must say "the record doesn't say" rather than showing a blank that
    # reads as zero.
    later_count_change: bool = False
    detected_at: datetime


class EnrollmentFinding(BaseModel):
    became_actual: List[EnrollmentMove] = []
    became_actual_total: int = 0
    # Of `became_actual_total`, how many enrolled fewer people than planned.
    under_target: int = 0
    # ACTUAL -> ESTIMATED: a real headcount reverting to a plan. Backwards,
    # rare (1 in the first eight days), and surfaced rather than dropped
    # for not fitting the expected direction.
    switched_back: List[EnrollmentMove] = []
    switched_back_total: int = 0
    target_raised: List[EnrollmentMove] = []
    target_raised_total: int = 0
    target_lowered: List[EnrollmentMove] = []
    target_lowered_total: int = 0


class ScopeExit(TrialRef):
    """A trial that left the watch. Nobody amended it — our filter stopped
    matching. `reason` is None when the stored data doesn't explain it,
    which renders as "we can't tell", never as a guess."""

    overall_status: Optional[str] = None
    reason: Optional[str] = None
    detected_at: datetime


class InvestigateWindow(BaseModel):
    """The denominators every finding below is measured against."""

    days: int
    since: datetime
    until: datetime
    # When the change record itself begins. A 90-day window over an 8-day
    # record must not report 82 quiet days nobody was watching.
    recording_since: Optional[datetime] = None
    covers_full_window: bool = False
    condition: Optional[str] = None
    trials_tracked: int
    trials_changed: int
    amendments: int
    field_changes: int


class InvestigateResponse(BaseModel):
    """Everything Investigate states about the window, in one response —
    the same shape /watch and /explore take, because these findings are
    read together and a slip count means something different depending on
    how many trials changed at all."""

    window: InvestigateWindow
    dates: List[DateMovement] = []
    lifecycle: List[LifecycleFinding] = []
    enrollment: EnrollmentFinding = EnrollmentFinding()
    # Leads the page. Not because it is the commonest finding — it is the
    # rarest — but because it is the only one a researcher cannot get from
    # the registry itself, and the one outside evidence says matters.
    outcomes: "OutcomeFinding"
    scope_exits: List[ScopeExit] = []
    scope_exits_total: int = 0


class OutcomeChange(TrialRef):
    """A change to a trial's registered primary outcome.

    **This is never an accusation, and the wording must stay that way.**
    Changing a registered endpoint has innocent explanations — a regulator
    asked, a typo was fixed, wording was standardised — and the record
    alone cannot say which. CLAUDE.md sec. 2's vocabulary applies exactly
    as it does to eligibility: what changed, when it changed relative to
    the trial's own milestones, and that it requires review. No verdict.

    `flags` are facts the record states, listed, not summed. A single
    confidence number would be the invisible ranking sec. 3 forbids and
    step 7 was removed for.

    `interpretation` is the stored model reading of the diff (step 7c),
    present for 5 of the record's outcome changes. **Its absence means
    three different things** the column cannot separate — the row predates
    2026-09-03, the model said MEANINGFUL: no, or it was never selected —
    so absence must never render as "nothing important changed".
    """

    # The measure names themselves, as the registry wrote them — the
    # evidence, not a summary of it (sec. 3).
    measures_added: List[str] = []
    measures_removed: List[str] = []
    count_before: int
    count_after: int
    # True when the measure names are identical after casefold and
    # punctuation stripping: the endpoint did not change, its wording did.
    # NCT03674567 in the live record is exactly this — "Safety and
    # tolerability" became "Safety and Tolerability" on a trial that has
    # posted results and is past primary completion, which is the
    # strongest flag combination available and still not a switch.
    wording_only: bool = False
    flags: List[str] = []
    flag_labels: List[str] = []
    interpretation: Optional[str] = None
    detected_at: datetime


class OutcomeFinding(BaseModel):
    """What the window says about registered primary outcomes moving."""

    changes: List[OutcomeChange] = []
    total: int = 0
    substantive: int = 0
    wording_only: int = 0
    # Substantive changes made after the trial's own primary completion
    # date — the signal the literature treats as real, because before that
    # date nobody has seen the endpoint data.
    after_primary_completion: int = 0
    unreadable: int = 0


InvestigateResponse.model_rebuild()


# ============================================================================
# Investigate — the landscape half (step 9, unit 2b)
# ============================================================================
#
# "What has been done in breast cancer?" is a different question from
# "what changed this week", and nothing in TrialLens answered it. Explore
# answers it one trial at a time; Monitor answers it one change at a time.
# This is the corpus-wide view, sliced by condition.


class LandscapeBucket(BaseModel):
    label: str
    count: int
    # Why this bucket cannot be read like its neighbours — "part year so
    # far", "planned start". A bar chart without these implies a decline
    # in the current year that is only the calendar.
    note: Optional[str] = None


class LandscapeCategory(BaseModel):
    """A distribution, with the share the registry never stated kept in it.

    `unstated` is the reason this is a model rather than a dict. 53% of
    breast-cancer trials report a phase of NA or nothing at all, and a
    phase chart that quietly drops them describes a different, tidier
    field than the one that exists (CLAUDE.md sec. 2).
    """

    buckets: List[LandscapeBucket] = []
    stated: int = 0
    unstated: int = 0
    unstated_label: Optional[str] = None

    @property
    def total(self) -> int:
        return self.stated + self.unstated


class InterventionUse(BaseModel):
    name: str
    type: str
    trials: int


class SponsorActivity(BaseModel):
    name: str
    trials: int


class LandscapeResponse(BaseModel):
    """What the tracked corpus looks like for one slice of it.

    Every list carries its own denominator, the same rule Explore's capped
    lists keep: `interventions_denominator` is the trials that list any
    intervention at all (4,938 of 5,377 for breast cancer), not the slice
    size, because a term's reach means nothing against the wrong total.
    """

    condition: Optional[str] = None
    trials: int
    started_per_year: List[LandscapeBucket] = []
    phases: LandscapeCategory = LandscapeCategory()
    statuses: LandscapeCategory = LandscapeCategory()
    enrollment_bands: List[LandscapeBucket] = []
    enrollment_stated: int = 0
    interventions: List[InterventionUse] = []
    interventions_denominator: int = 0
    sponsors: List[SponsorActivity] = []
    results_posted: int = 0


class LandscapeTrial(TrialRef):
    """One trial behind a landscape bar — what a reader gets for clicking it."""

    overall_status: str
    phase: Optional[str] = None
    enrollment_count: Optional[int] = None
    start_date: Optional[str] = None
    has_results: Optional[bool] = None


class LandscapeTrials(BaseModel):
    """The trials behind one bar, capped, with its real total.

    Same rule as every other capped list in this project: the total comes
    from `count(*) OVER ()`, which runs before LIMIT, so the honest number
    costs no extra round trip and a short list never reads as a complete one.
    """

    intervention: Optional[str] = None
    condition: Optional[str] = None
    trials: List[LandscapeTrial] = []
    total: int = 0

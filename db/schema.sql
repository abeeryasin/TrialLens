-- TrialLens core schema.
-- Source of truth for a study record: ClinicalTrials.gov v2 API.
-- raw_json preserves the untouched API response; the other columns are
-- normalized values pulled out of it for fast querying (see docs/decisions.md).

CREATE TABLE IF NOT EXISTS studies (
    nct_id                    TEXT PRIMARY KEY,
    brief_title               TEXT NOT NULL,
    official_title            TEXT,
    overall_status            TEXT NOT NULL,
    study_type                TEXT,
    phase                     TEXT,
    enrollment_count          INTEGER,
    sex                       TEXT,
    minimum_age               TEXT,
    healthy_volunteers        BOOLEAN,
    eligibility_criteria      TEXT,
    last_update_post_date     DATE NOT NULL,
    raw_json                  JSONB NOT NULL,
    fetched_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    active_in_scope           BOOLEAN NOT NULL DEFAULT true,
    last_matched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    brief_summary              TEXT,
    lead_sponsor                TEXT,
    start_date                  TEXT,
    primary_completion_date     TEXT,
    completion_date             TEXT,
    interventions                JSONB,
    primary_outcomes             JSONB,
    locations                    JSONB
);

-- ADD COLUMN IF NOT EXISTS so this file stays the one idempotent source of
-- truth (scripts/apply_schema.py just re-runs it) even against a database
-- that already has the table from before these columns existed.
ALTER TABLE studies ADD COLUMN IF NOT EXISTS active_in_scope BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS last_matched_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Narrative/design fields (2026-08-29, see docs/decisions.md): "why does
-- this trial matter" needs more than title+eligibility+status. All of this
-- already exists in raw_json for every stored trial — these columns exist
-- so it's normalized, diffable (Monitor can report a real change to an
-- outcome measure, not just to last_update_post_date), and queryable
-- without unpacking JSON on every read.
--
-- start/primary_completion/completion date are TEXT, not DATE: verified
-- live against a real sample (2026-08-29) that ~23% of trials report these
-- at month-only precision ("2027-06", no day) — a DATE column would either
-- reject those rows or force inventing a day CT.gov never specified, which
-- CLAUDE.md sec. 2 explicitly forbids (never invent a study fact).
-- last_update_post_date stays DATE: CT.gov always reports it at full
-- day precision (unlike these three), confirmed by 11k+ existing rows
-- having ingested cleanly under a NOT NULL DATE column already.
ALTER TABLE studies ADD COLUMN IF NOT EXISTS brief_summary TEXT;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS lead_sponsor TEXT;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS start_date TEXT;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS primary_completion_date TEXT;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS completion_date TEXT;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS interventions JSONB;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS primary_outcomes JSONB;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS locations JSONB;

-- ACTUAL vs ESTIMATED (2026-08-29): enrollment_count alone can't be read
-- honestly — "34" is either 34 people actually enrolled or a recruitment
-- target, and most CT.gov records are the latter. Stored so the UI can say
-- which, and diffed so a target-becomes-actual switch is itself reportable.
ALTER TABLE studies ADD COLUMN IF NOT EXISTS enrollment_type TEXT;

-- Upper age bound (2026-08-30). minimum_age alone can only ever show "18
-- Years and older", which is a lower bound, not the trial's actual age
-- bracket. TEXT, not a number: CT.gov reports these with their unit
-- attached and the unit genuinely varies ("18 Years", "18 Months").
ALTER TABLE studies ADD COLUMN IF NOT EXISTS maximum_age TEXT;

-- One-off fix: the three date columns above were first applied as DATE
-- (2026-08-29) before the month-only-precision check above was run — no
-- rows had been written to them yet, so no data-loss risk. Uses DROP+ADD
-- rather than ALTER COLUMN TYPE: a type change forces Postgres to rewrite
-- every row of the table even for an all-NULL column, which briefly
-- exceeded Neon's free-tier project size limit in practice; DROP+ADD on
-- an empty column is cheap. Guarded to only run if still DATE, so this
-- stays idempotent and is a no-op on a fresh database that never had the
-- wrong type.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'studies' AND column_name = 'start_date' AND data_type = 'date'
    ) THEN
        ALTER TABLE studies DROP COLUMN start_date;
        ALTER TABLE studies DROP COLUMN primary_completion_date;
        ALTER TABLE studies DROP COLUMN completion_date;
        ALTER TABLE studies ADD COLUMN start_date TEXT;
        ALTER TABLE studies ADD COLUMN primary_completion_date TEXT;
        ALTER TABLE studies ADD COLUMN completion_date TEXT;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS study_conditions (
    id        SERIAL PRIMARY KEY,
    nct_id    TEXT NOT NULL REFERENCES studies(nct_id),
    condition TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_study_conditions_nct_id ON study_conditions(nct_id);

-- Real change history: written by the "expensive diff" step in
-- api/studies.py whenever a re-ingested field differs from what's stored,
-- so Monitor can report what changed, not just refresh silently overwrite it
-- (see docs/decisions.md, 2026-08-28).
CREATE TABLE IF NOT EXISTS study_changes (
    id           SERIAL PRIMARY KEY,
    nct_id       TEXT NOT NULL REFERENCES studies(nct_id),
    field_name   TEXT NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_study_changes_nct_id ON study_changes(nct_id);

-- Prose interpretation (step 7c): stores AI interpretation of eligibility/summary/outcome changes
-- JSON: {summary} from interpret_prose_change(). why_matters was dropped
-- 2026-09-04: it was ~48% of output tokens and carried every weak line in the
-- first live batch — speculation about consequences sitting beside
-- source-anchored fact with the same authority. A clinical researcher judges
-- significance; the model's job is to spot the change (docs/decisions.md).
ALTER TABLE study_changes ADD COLUMN IF NOT EXISTS prose_interpretation JSONB;

-- Supports the Monitor page's aggregate feed (GET /changes, step 6,
-- 2026-08-29): that query orders by detected_at DESC across ALL trials,
-- not filtered to one nct_id, so idx_study_changes_nct_id alone doesn't
-- help it. Added now rather than waiting for the table to grow, per
-- explicit decision the same day.
CREATE INDEX IF NOT EXISTS idx_study_changes_detected_at ON study_changes(detected_at DESC);

-- Whether ClinicalTrials.gov has posted RESULTS for this trial (2026-09-02).
-- Stored and diffed because false -> true is the single most consequential
-- amendment a researcher can receive: the trial's findings are out. It lives
-- at the TOP level of the API response (`hasResults`), not inside
-- protocolSection, which is why the first pass over the record missed it —
-- 1,056 of 11,518 stored trials already have it true, 751 of them completed,
-- and every one of those amendments was previously reported as "amended, but
-- we can't see what". See docs/decisions.md, 2026-09-02.
ALTER TABLE studies ADD COLUMN IF NOT EXISTS has_results BOOLEAN;

-- Monitor run record (step 7b direction 3). Every scheduled fetch records
-- when it started, when it completed, and what it found. This replaces the
-- proxy `max(studies.last_matched_at)` so the watch knows a run happened
-- even on a quiet day (no amendments). The proxy was read-only evidence
-- that a check occurred; this table makes that evidence explicit and durable.
CREATE TABLE IF NOT EXISTS monitor_runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running',
    trials_checked  INTEGER,
    changes_detected INTEGER
);
CREATE INDEX IF NOT EXISTS idx_monitor_runs_completed_at ON monitor_runs(completed_at DESC);

-- What step 7c actually spent on this run (2026-09-03). NUMERIC, never a
-- float: money summed across 120 runs a month should not accumulate binary
-- rounding error in the value a spend ceiling is compared against.
--
-- This column IS the rolling budget. run_monitor.rolling_budget_remaining()
-- sums it over the last 30 days and refuses to call when the ceiling is
-- reached, because PROSE_BUDGET_USD only ever bounded ONE run and a 6-hourly
-- cron makes 120 of them a month. Recording it rather than holding a counter
-- in memory means the window survives restarts and stays auditable.
--
-- Summed by `started_at`, so a run that spent money and then crashed before
-- completing still counts against the ceiling.
--
-- NULL on runs from before this existed, and on run #1 which was backfilled
-- from a proxy. coalesce(...,0) in the sum treats those as "no spend
-- recorded", which is true: step 7c had never run.
ALTER TABLE monitor_runs ADD COLUMN IF NOT EXISTS prose_spend_usd NUMERIC(10, 4);
CREATE INDEX IF NOT EXISTS idx_monitor_runs_started_at ON monitor_runs(started_at DESC);

-- ---------------------------------------------------------------------------
-- Explore / knowledge graph (step 8 unit 2, 2026-09-03).
--
-- These tables do not create a graph; they make the one already in `studies`
-- walkable. `lead_sponsor` holding 'Mayo Clinic' on 134 rows is already 134
-- edges — written as a repeated string, which is awkward to traverse and
-- impossible to attach anything to. See docs/decisions.md, 2026-09-02, for
-- why this is relational tables rather than a graph database.
--
-- NOTHING HERE IS MERGED. Every distinct source string gets its own row, so
-- 381 Madrid facility strings become 381 sites and 55 semaglutide names
-- become 55 terms. That is deliberate: merging is a decision about the data
-- and belongs in its own reversible step, checked against this unmerged
-- extraction as the baseline. Extracting and merging in one pass would leave
-- no record of what the registry actually said (CLAUDE.md sec. 3).
-- ---------------------------------------------------------------------------

-- ONE table for lead sponsors and collaborators, not two. Measured
-- 2026-09-03: 887 of the 3,915 distinct collaborator names are also lead
-- sponsors on other trials. Bristol-Myers Squibb leading one trial and
-- collaborating on another is one organization in two roles — split into
-- two tables it becomes two nodes, and "who else works with them?" silently
-- returns half the answer. The role lives on the edge, where it belongs.
CREATE TABLE IF NOT EXISTS organizations (
    id      SERIAL PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS trial_organizations (
    nct_id     TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
    org_id     INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,   -- 'LEAD' | 'COLLABORATOR'
    -- INDUSTRY / OTHER_GOV / NIH / ... as reported on THIS trial. Kept on the
    -- edge rather than the organization because that is what the source says;
    -- one org can be filed under different classes by different registrants,
    -- and picking a winner would invent a fact (CLAUDE.md sec. 2).
    org_class  TEXT,
    PRIMARY KEY (nct_id, org_id, role)
);

-- Identity is the (facility, city, country) triple, not the facility name:
-- the same name recurs in different cities. 142,698 location mentions
-- collapse to 51,233 distinct triples (measured 2026-09-03). 24 mentions
-- have no facility and 1 has no city, so the identity index coalesces —
-- a plain UNIQUE would treat every NULL as distinct and duplicate them.
CREATE TABLE IF NOT EXISTS sites (
    id        SERIAL PRIMARY KEY,
    facility  TEXT,
    city      TEXT,
    country   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sites_identity
    ON sites (coalesce(facility, ''), coalesce(city, ''), coalesce(country, ''));

CREATE TABLE IF NOT EXISTS trial_sites (
    nct_id   TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
    site_id  INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    PRIMARY KEY (nct_id, site_id)
);

-- Identity is (name, affiliation). Name alone is not enough: 286 investigator
-- names appear under more than one affiliation (measured 2026-09-03), and
-- keying on name would merge people who may be different people — the exact
-- Procrustean cut this step is supposed to avoid. Only 10 of 9,228 mentions
-- carry no affiliation at all.
CREATE TABLE IF NOT EXISTS investigators (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    affiliation  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_investigators_identity
    ON investigators (name, coalesce(affiliation, ''));

CREATE TABLE IF NOT EXISTS trial_investigators (
    nct_id           TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
    investigator_id  INTEGER NOT NULL REFERENCES investigators(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,  -- PRINCIPAL_INVESTIGATOR | STUDY_DIRECTOR | STUDY_CHAIR
    PRIMARY KEY (nct_id, investigator_id, role)
);

-- "term", not "intervention": these are surface forms as the registry
-- received them, not canonical drugs. 13,307 distinct names, 11,598 of them
-- used exactly once. Identity is (name, type) because 363 names appear under
-- more than one type, and a DRUG called X is not the OTHER called X.
CREATE TABLE IF NOT EXISTS intervention_terms (
    id     SERIAL PRIMARY KEY,
    name   TEXT NOT NULL,
    type   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_intervention_terms_identity
    ON intervention_terms (name, type);

CREATE TABLE IF NOT EXISTS trial_interventions (
    nct_id   TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
    term_id  INTEGER NOT NULL REFERENCES intervention_terms(id) ON DELETE CASCADE,
    PRIMARY KEY (nct_id, term_id)
);

-- Each edge table's PRIMARY KEY indexes nct_id first, which answers "what
-- does this trial connect to". The reverse — "which trials connect to this
-- organization/site/person/term" — is the direction Explore actually walks,
-- and without these it is a sequential scan every hop.
CREATE INDEX IF NOT EXISTS idx_trial_organizations_org ON trial_organizations(org_id);
CREATE INDEX IF NOT EXISTS idx_trial_sites_site ON trial_sites(site_id);
CREATE INDEX IF NOT EXISTS idx_trial_investigators_inv ON trial_investigators(investigator_id);
CREATE INDEX IF NOT EXISTS idx_trial_interventions_term ON trial_interventions(term_id);

-- ---------------------------------------------------------------------------
-- Delisted edges (2026-09-03).
--
-- Trials drop sites, swap investigators and retire intervention arms. The
-- extraction only ever INSERTs, so without this an edge outlives the record
-- that justified it: one 6-hour monitor run left 15 trial_sites edges whose
-- trial no longer lists that location, and Explore would have gone on saying
-- the trial runs there. That is a connection the registry does not state
-- (CLAUDE.md sec. 2).
--
-- Deleting them would fix the lie and destroy the finding. This is a
-- watch-over-time product: "this trial quietly dropped three sites" is a
-- result, not an error, and sec. 3 wants the evidence kept rather than
-- silently reconciled away. So the edge stays and carries the date the
-- backfill first saw it gone.
--
-- NULL means live — the connection is in the current record. A timestamp is
-- the first run that could not find it. It is NOT the date the trial made
-- the change; nothing on file says that, and writing the real amendment date
-- here would be inventing precision the backfill does not have. Query
-- `WHERE delisted_at IS NULL` for the graph as it stands today.
--
-- An edge that comes back (a site re-listed) has its stamp cleared, which is
-- why the backfill's ON CONFLICT clauses are DO UPDATE rather than DO
-- NOTHING. Entity rows are never delisted: a delisted edge still points at
-- its site, and the site was genuinely reported once.
-- ---------------------------------------------------------------------------
-- Renamed from `withdrawn_at` on 2026-09-03, hours after it was created.
-- CT.gov's own per-site vocabulary contains the value 'WITHDRAWN' meaning
-- "the site withdrew before enrolling anyone", which is a completely
-- different fact from "the record stopped listing this location". One word
-- for two meanings in one table is a trap, and it was cheaper to remove it
-- than to keep explaining it — at the time of the rename nothing outside
-- this file, the backfill and its tests read the column.
--
-- The rename must run BEFORE the ADD COLUMN below, or a database that
-- already has `withdrawn_at` would get a second, empty `delisted_at`
-- alongside it and quietly lose 17 stamped edges. Guarded so the whole file
-- stays idempotent: it renames on a database that still has the old name,
-- and does nothing on a fresh one or on a second run.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['trial_organizations', 'trial_sites',
                             'trial_investigators', 'trial_interventions']
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = t
                     AND column_name = 'withdrawn_at')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = 'public' AND table_name = t
                             AND column_name = 'delisted_at')
        THEN
            EXECUTE format('ALTER TABLE %I RENAME COLUMN withdrawn_at TO delisted_at', t);
        END IF;
    END LOOP;
END $$;

ALTER TABLE trial_organizations ADD COLUMN IF NOT EXISTS delisted_at TIMESTAMPTZ;
ALTER TABLE trial_sites         ADD COLUMN IF NOT EXISTS delisted_at TIMESTAMPTZ;
ALTER TABLE trial_investigators ADD COLUMN IF NOT EXISTS delisted_at TIMESTAMPTZ;
ALTER TABLE trial_interventions ADD COLUMN IF NOT EXISTS delisted_at TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- Site enrichment (2026-09-03) — the fields the parser dropped.
--
-- `locations` was normalized down to facility/city/country and everything
-- else discarded, so these have sat unread in raw_json since ingestion. The
-- third time that has happened after `has_results` and the overallOfficials
-- the graph extraction found. Measured across 142,777 stored locations:
-- geoPoint on 140,285 (98.3%), zip on 133,069, state on 99,609, and a
-- per-location `status` on 41,027.
--
-- Why these and not more of the graph: the evidence review on 2026-09-03
-- (docs/plan_explore_nodes.md) put sites first among Explore's node types.
-- Sites reach 93.8% of trials against the collaborator edge's 37.4%, and the
-- documented clinician workflow is "search, find a candidate trial, then
-- phone the site to ask whether it is still open." `recruitment_status`
-- answers that question from data already on file.
--
-- NO NETWORK CALL. Backfilled from stored raw_json (CLAUDE.md sec. 4).
-- ---------------------------------------------------------------------------

-- Place attributes, so they live on the site rather than the edge.
--
-- Populated ONLY where every record reporting this site agrees. The registry
-- genuinely disagrees with itself: 109 site identities carry more than one
-- geoPoint, and the disagreement is not rounding — 103 of them are 5km or
-- more apart and the largest is 52 degrees, the same facility string placed
-- on different continents. Rounding to 4 decimal places removes none of
-- them. Picking a winner would put a trial in the wrong country on a
-- "near me" map, so a disputed value is left NULL and counted, the same
-- "we can't tell" the tracking drop reasons use rather than a guess
-- (CLAUDE.md sec. 2). 49,650 of 51,272 sites get coordinates; zip disagrees
-- on 3,344 identities and state on 484.
ALTER TABLE sites ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS zip   TEXT;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS lat   DOUBLE PRECISION;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS lon   DOUBLE PRECISION;

-- Recruitment status is a property of the EDGE, not the site, and the data
-- settles it: 2,616 site identities report more than one status across the
-- trials that use them. Of course they do — a hospital recruiting for one
-- trial and closed for another is one place in two states. Stored on
-- trial_sites for the same reason organization role is stored on its edge.
--
-- NULL means the registry gave no per-location status, which is the common
-- case: only 40,183 of 140,037 edges carry one, because CT.gov mostly
-- supplies it for actively recruiting studies. NULL is "not stated", never
-- "not recruiting" — anything reading this column must keep that distinction
-- or it will report closed sites that were merely silent.
--
-- 172 (trial, site) pairs report two different statuses at once, a trial
-- listing the same facility twice; those are left NULL and counted too.
--
-- NAMING TRAP: one of the values CT.gov uses here is literally 'WITHDRAWN',
-- and this table also has a `delisted_at` column. They are unrelated.
-- recruitment_status = 'WITHDRAWN' is the registry saying the site withdrew
-- from the trial before enrolling anyone. `delisted_at` is OURS, and means
-- the trial's record stopped listing this location at all. A site can be
-- live (delisted_at IS NULL) while its recruitment_status reads 'WITHDRAWN'.
ALTER TABLE trial_sites ADD COLUMN IF NOT EXISTS recruitment_status TEXT;

-- ---------------------------------------------------------------------------
-- Entity merging (step 8 unit 3, 2026-09-04).
--
-- Units 1-2 extracted everything unmerged ON PURPOSE, so that the registry's
-- own words survived and any later merge had a baseline to be checked
-- against. This is that later merge, and it is deliberately the smallest
-- thing that works: a POINTER, never a delete.
--
-- NULL means "this row is its own canonical form" — the overwhelming
-- majority. A value points at the id of the row chosen to represent the
-- group. Read identity as `coalesce(canonical_id, id)` everywhere.
--
-- Nothing is removed and no edge is rewritten, so the unmerged extraction
-- is still exactly on file and the whole merge is undone by setting this
-- column back to NULL. That matters because merging is a JUDGEMENT about
-- the data — "these two strings are one thing" — and a judgement written
-- destructively cannot be revisited (CLAUDE.md sec. 3 and 4).
--
-- WHAT COUNTS AS THE SAME THING is deterministic and deliberately timid:
-- casefold, replace every non-alphanumeric run with a single space, trim.
-- Nothing else. No fuzzy distance, no abbreviation expansion, no model.
-- 'Sun Yat-Sen University Cancer Center' and 'Sun yat sen university
-- cancer center' merge (11 real spellings of that one Guangzhou hospital);
-- 'Semaglutide' and 'semaglutide' merge, while 'Placebo semaglutide' and
-- 'Semaglutide 2.4 mg' correctly do NOT — a placebo arm is not the drug,
-- and a dose is not the same intervention.
--
-- Measured 2026-09-04 before writing any of this:
--   sites               2,395 groups, 3,033 rows collapsed of 51,317 (5.9%)
--   intervention_terms    650 groups,   783 rows collapsed
--   investigators          99 groups,   111 rows collapsed
--   organizations           0 groups — ALREADY CLEAN, so it gets no column.
--
-- That last line is why this is scoped the way it is. The obvious symmetric
-- design gives all four tables the same treatment; the data says one of
-- them has nothing to fix, and building it anyway would be a merge with no
-- duplicates to merge.
--
-- Sites merge on the (facility, city, country) TRIPLE, never on facility
-- alone: the same hospital name genuinely recurs in different cities, and
-- collapsing those would move a trial to another country. The 381 Madrid
-- facility strings that motivated this column are, on inspection, 381
-- different Madrid hospitals — not 381 spellings of one.
-- ---------------------------------------------------------------------------
ALTER TABLE sites              ADD COLUMN IF NOT EXISTS canonical_id INTEGER REFERENCES sites(id);
ALTER TABLE intervention_terms ADD COLUMN IF NOT EXISTS canonical_id INTEGER REFERENCES intervention_terms(id);
ALTER TABLE investigators      ADD COLUMN IF NOT EXISTS canonical_id INTEGER REFERENCES investigators(id);

-- Explore groups by canonical identity on every read, so these carry the
-- same weight as the reverse-direction edge indexes above.
CREATE INDEX IF NOT EXISTS idx_sites_canonical              ON sites(canonical_id);
CREATE INDEX IF NOT EXISTS idx_intervention_terms_canonical ON intervention_terms(canonical_id);
CREATE INDEX IF NOT EXISTS idx_investigators_canonical      ON investigators(canonical_id);

-- ---------------------------------------------------------------------------
-- Weekly synthesis agent (step 9 follow-on, 2026-09-04/05).
--
-- The one genuinely multi-step judgment in the product: "is this week's
-- movement a pattern or a coincidence?" Investigate's numbers are exactly
-- checkable (CLAUDE.md sec. 5) but do not compare themselves across weeks
-- or decide which of several true facts is worth a researcher's attention —
-- that reasoning is the agent's job, once a week, reading /investigate and
-- /investigate/landscape as its only tools. See docs/decisions.md,
-- 2026-09-04, for the costing that ruled out a multi-agent crew.
-- ---------------------------------------------------------------------------

-- Run record, same shape as monitor_runs and for the same reason: the
-- ceiling below sums `spend_usd` over `started_at`, so a run that spent
-- money and then failed before finishing is still counted rather than
-- becoming invisible to its own budget guard.
CREATE TABLE IF NOT EXISTS synthesis_runs (
    id                 SERIAL PRIMARY KEY,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    status             TEXT NOT NULL DEFAULT 'running',
    proposals_created  INTEGER,
    spend_usd          NUMERIC(10, 4)
);
CREATE INDEX IF NOT EXISTS idx_synthesis_runs_started_at ON synthesis_runs(started_at DESC);

-- What the agent proposes, never what it decides. A proposal sits here
-- until a person accepts or dismisses it — this table IS the review queue
-- named in CLAUDE.md's "Current Status", and per sec. 3 every row carries
-- its evidence, not just its conclusion: `evidence` holds the tool results
-- the agent actually read, so "why does the agent think this" is answered
-- by the row itself rather than by trusting the summary.
--
-- `confidence` is a label (high/medium/low), never a number — sec. 3 and
-- the step-7 removal both rule out an unexplained score. Two labels of the
-- same finding a week apart are two rows: nothing here is ever overwritten,
-- so a reviewer can see the agent changed its mind, not just its current
-- opinion.
CREATE TABLE IF NOT EXISTS review_queue (
    id             SERIAL PRIMARY KEY,
    run_id         INTEGER REFERENCES synthesis_runs(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    window_since   TIMESTAMPTZ NOT NULL,
    window_until   TIMESTAMPTZ NOT NULL,
    finding_type   TEXT NOT NULL,
    summary        TEXT NOT NULL,
    evidence       JSONB NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'dismissed')),
    reviewed_at    TIMESTAMPTZ,
    reviewed_note  TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status, created_at DESC);

-- ---------------------------------------------------------------------------
-- Tracked conditions (step 10, 2026-09-05).
--
-- Replaces config/tracked_conditions.json. Adding a condition to watch used
-- to mean editing a file and redeploying; this table is the real registry
-- instead, so a researcher can add one through the UI and the next Monitor
-- run (scripts/run_monitor.py) picks it up without a code change. Seeded
-- from the file's two real entries by scripts/backfill_tracked_conditions.py,
-- not by this migration — schema.sql defines structure only elsewhere in
-- this project, real data population is a separate one-off script.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tracked_conditions (
    id         SERIAL PRIMARY KEY,
    condition  TEXT NOT NULL UNIQUE,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

-- Supports the Monitor page's aggregate feed (GET /changes, step 6,
-- 2026-08-29): that query orders by detected_at DESC across ALL trials,
-- not filtered to one nct_id, so idx_study_changes_nct_id alone doesn't
-- help it. Added now rather than waiting for the table to grow, per
-- explicit decision the same day.
CREATE INDEX IF NOT EXISTS idx_study_changes_detected_at ON study_changes(detected_at DESC);

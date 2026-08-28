-- TrialLens core schema.
-- Source of truth for a study record: ClinicalTrials.gov v2 API.
-- raw_json preserves the untouched API response; the other columns are
-- normalized values pulled out of it for fast querying (see docs/decisions.md).

CREATE TABLE IF NOT EXISTS studies (
    nct_id                 TEXT PRIMARY KEY,
    brief_title            TEXT NOT NULL,
    official_title         TEXT,
    overall_status         TEXT NOT NULL,
    study_type             TEXT,
    phase                  TEXT,
    enrollment_count       INTEGER,
    sex                    TEXT,
    minimum_age            TEXT,
    healthy_volunteers     BOOLEAN,
    eligibility_criteria   TEXT,
    last_update_post_date  DATE NOT NULL,
    raw_json               JSONB NOT NULL,
    fetched_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    active_in_scope        BOOLEAN NOT NULL DEFAULT true,
    last_matched_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ADD COLUMN IF NOT EXISTS so this file stays the one idempotent source of
-- truth (scripts/apply_schema.py just re-runs it) even against a database
-- that already has the table from before these two columns existed.
ALTER TABLE studies ADD COLUMN IF NOT EXISTS active_in_scope BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE studies ADD COLUMN IF NOT EXISTS last_matched_at TIMESTAMPTZ NOT NULL DEFAULT now();

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

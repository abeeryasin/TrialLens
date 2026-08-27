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
    fetched_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS study_conditions (
    id        SERIAL PRIMARY KEY,
    nct_id    TEXT NOT NULL REFERENCES studies(nct_id),
    condition TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_study_conditions_nct_id ON study_conditions(nct_id);

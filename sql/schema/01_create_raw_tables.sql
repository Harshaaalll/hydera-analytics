-- ============================================================
-- HydRERA Analytics — Raw Table Schema
-- Run this ONCE after: createdb hydera_rera
-- ============================================================

DROP TABLE IF EXISTS raw_rera_projects CASCADE;
DROP TABLE IF EXISTS raw_rera_complaints CASCADE;
DROP TABLE IF EXISTS raw_property_registrations CASCADE;

-- 1. RERA Projects
CREATE TABLE raw_rera_projects (
    project_id                  TEXT PRIMARY KEY,
    project_name                TEXT,
    builder_name                TEXT,
    district                    TEXT,
    locality                    TEXT,
    project_type                TEXT,
    approved_units              INTEGER,
    registration_date           DATE,
    expected_completion_date    DATE,
    actual_completion_date      DATE,
    project_status              TEXT,
    _loaded_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_projects_builder  ON raw_rera_projects(builder_name);
CREATE INDEX idx_projects_locality ON raw_rera_projects(locality);
CREATE INDEX idx_projects_status   ON raw_rera_projects(project_status);

-- 2. RERA Complaints
CREATE TABLE raw_rera_complaints (
    complaint_id                TEXT PRIMARY KEY,
    builder_name                TEXT,
    project_name                TEXT,
    complaint_category          TEXT,
    complaint_date              DATE,
    resolution_status           TEXT,
    days_to_resolution          INTEGER,
    _loaded_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_complaints_builder ON raw_rera_complaints(builder_name);

-- 3. Property Registrations (Sale Deeds)
CREATE TABLE raw_property_registrations (
    transaction_id              TEXT PRIMARY KEY,
    locality                    TEXT,
    district                    TEXT,
    registration_date           DATE,
    area_sqft                   NUMERIC(12,2),
    total_price_inr             NUMERIC(16,2),
    price_per_sqft              NUMERIC(10,2),
    property_type               TEXT,
    _loaded_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tx_locality ON raw_property_registrations(locality);
CREATE INDEX idx_tx_date     ON raw_property_registrations(registration_date);
CREATE INDEX idx_tx_psf      ON raw_property_registrations(price_per_sqft);

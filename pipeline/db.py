"""SQLite store. Schema mirrors schema/models.py; nothing else writes here."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "corpus.sqlite"

DDL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_tier INTEGER NOT NULL,
    publisher TEXT,
    title TEXT,
    authored_by_subject INTEGER NOT NULL,
    utterance_date TEXT,
    publication_date TEXT,
    date_precision TEXT,
    language TEXT,
    raw_path TEXT,
    raw_content_hash TEXT,
    text TEXT,
    collector TEXT,
    fetched_at TEXT,
    audience TEXT,
    transcript_segments TEXT,
    license_note TEXT,
    access_ok INTEGER NOT NULL DEFAULT 1,
    fetch_error TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_canonical ON documents(canonical_url);
CREATE INDEX IF NOT EXISTS idx_documents_person_date ON documents(person_id, utterance_date);

CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    person_id TEXT NOT NULL,
    date TEXT NOT NULL,
    date_precision TEXT,
    supporting_text TEXT NOT NULL,
    normalized_claim TEXT NOT NULL,
    topics TEXT,
    axis_scores TEXT,
    hedged INTEGER,
    locator TEXT,
    timeline_years REAL,
    agi_definition TEXT,
    corroborating_urls TEXT,
    extractor_model TEXT,
    rubric_version TEXT,
    extracted_at TEXT,
    human_reviewed INTEGER DEFAULT 0,
    CHECK (length(trim(supporting_text)) > 0)
);
CREATE INDEX IF NOT EXISTS idx_claims_person_date ON claims(person_id, date);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, date TEXT NOT NULL, date_precision TEXT,
    title TEXT NOT NULL, summary TEXT, category TEXT NOT NULL,
    importance INTEGER NOT NULL, people TEXT, orgs TEXT, sources TEXT,
    ai_attributed_by_company INTEGER,
    CHECK (importance BETWEEN 1 AND 5)
);

CREATE TABLE IF NOT EXISTS polls (
    poll_id TEXT PRIMARY KEY, pollster TEXT NOT NULL, series_id TEXT NOT NULL,
    field_start TEXT, field_end TEXT, population TEXT, n INTEGER,
    question_text TEXT NOT NULL, results TEXT, axis TEXT, mapped_score REAL,
    mapping_note TEXT, source_url TEXT, margin_of_error REAL,
    wording_changed_from_prior INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS positions (
    person_id TEXT NOT NULL, axis TEXT NOT NULL, at_month TEXT NOT NULL,
    value REAL, n_claims INTEGER, evidence_mass REAL, dispersion REAL,
    status TEXT NOT NULL, contributing_claim_ids TEXT,
    PRIMARY KEY (person_id, axis, at_month)
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(DDL)
    print(f"initialised {DB_PATH}")


if __name__ == "__main__":
    init()

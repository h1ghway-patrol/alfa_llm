CREATE TABLE IF NOT EXISTS company (
    id               TEXT PRIMARY KEY,
    okved_code       TEXT,
    okved_name       TEXT,
    city             TEXT,
    region           TEXT,
    revenue_rub      REAL,
    revenue_band     TEXT,
    employees_band   TEXT,
    age_band         TEXT,
    ownership        TEXT,
    business_stage   TEXT,
    client_type      TEXT,
    has_loan         INTEGER CHECK (has_loan      IN (0,1)),
    has_leasing      INTEGER CHECK (has_leasing   IN (0,1)),
    has_guarantee    INTEGER CHECK (has_guarantee IN (0,1)),
    has_deposit      INTEGER CHECK (has_deposit   IN (0,1)),
    has_rko          INTEGER CHECK (has_rko       IN (0,1)),
    has_payroll      INTEGER CHECK (has_payroll   IN (0,1)),
    has_factoring    INTEGER CHECK (has_factoring IN (0,1)),
    has_fts          INTEGER CHECK (has_fts       IN (0,1)),
    fts_countries    TEXT,
    group_id         TEXT,
    group_size       INTEGER,
    key_owner_mark   INTEGER CHECK (key_owner_mark IN (0,1)),
    is_large         INTEGER NOT NULL DEFAULT 0 CHECK (is_large IN (0,1)),
    is_demo          INTEGER NOT NULL DEFAULT 0 CHECK (is_demo  IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_company_large ON company(is_large);
CREATE INDEX IF NOT EXISTS idx_company_demo  ON company(is_demo);
CREATE INDEX IF NOT EXISTS idx_company_group ON company(group_id);

CREATE TABLE IF NOT EXISTS payment (
    payer       TEXT NOT NULL,
    beneficiary TEXT NOT NULL,
    amount_rub  REAL NOT NULL,
    cnt         INTEGER NOT NULL,
    PRIMARY KEY (payer, beneficiary)
);
CREATE INDEX IF NOT EXISTS idx_payment_beneficiary ON payment(beneficiary);

CREATE TABLE IF NOT EXISTS counterparty (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    f_id        TEXT NOT NULL,
    client_id   TEXT,
    city_name   TEXT,
    region_name TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_counterparty_pair ON counterparty(f_id, COALESCE(client_id, ''));
CREATE INDEX IF NOT EXISTS idx_counterparty_f      ON counterparty(f_id);
CREATE INDEX IF NOT EXISTS idx_counterparty_client ON counterparty(client_id);

CREATE TABLE IF NOT EXISTS document (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL CHECK (kind IN ('bank','news')),
    title        TEXT NOT NULL,
    doc_date     TEXT,
    source_name  TEXT,
    url          TEXT,
    status       TEXT NOT NULL DEFAULT 'unknown'
                 CHECK (status IN ('actual','outdated','unknown')),
    content_hash TEXT NOT NULL UNIQUE,
    facts_json   TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_document_kind_date ON document(kind, doc_date);

CREATE TABLE IF NOT EXISTS doc_topic (
    doc_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    topic  TEXT NOT NULL,
    PRIMARY KEY (doc_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_doc_topic_topic ON doc_topic(topic);

CREATE TABLE IF NOT EXISTS chunk (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    section_path TEXT,
    position     INTEGER NOT NULL,
    text         TEXT NOT NULL,
    lemmas       TEXT NOT NULL DEFAULT '',
    UNIQUE (doc_id, position)
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    lemmas,
    content='chunk',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 0'
);
CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(rowid, lemmas) VALUES (new.id, new.lemmas);
END;
CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, lemmas) VALUES ('delete', old.id, old.lemmas);
END;
CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, lemmas) VALUES ('delete', old.id, old.lemmas);
    INSERT INTO chunk_fts(rowid, lemmas) VALUES (new.id, new.lemmas);
END;

CREATE TABLE IF NOT EXISTS relevance (
    client_id    TEXT NOT NULL REFERENCES company(id)  ON DELETE CASCADE,
    doc_id       INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    score        REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    computed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (client_id, doc_id)
);
CREATE INDEX IF NOT EXISTS idx_relevance_doc ON relevance(doc_id);

CREATE TABLE IF NOT EXISTS run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT NOT NULL REFERENCES company(id)  ON DELETE CASCADE,
    doc_id      INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','done','failed')),
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_client ON run(client_id);

CREATE TABLE IF NOT EXISTS insight (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  TEXT NOT NULL REFERENCES company(id)  ON DELETE CASCADE,
    doc_id     INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    run_id     INTEGER REFERENCES run(id) ON DELETE SET NULL,
    status     TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('done','failed')),
    body_json  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (client_id, doc_id)
);

CREATE TABLE IF NOT EXISTS insight_source (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_id     INTEGER NOT NULL REFERENCES insight(id) ON DELETE CASCADE,
    claim_key      TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('fact','bank','ai','client')),
    chunk_id       INTEGER REFERENCES chunk(id)    ON DELETE SET NULL,
    doc_id         INTEGER REFERENCES document(id) ON DELETE SET NULL,
    client_feature TEXT
);
CREATE INDEX IF NOT EXISTS idx_insight_source_insight ON insight_source(insight_id);
CREATE INDEX IF NOT EXISTS idx_insight_source_chunk   ON insight_source(chunk_id);

CREATE TABLE IF NOT EXISTS trace_step (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    step_no     INTEGER NOT NULL,
    step_type   TEXT NOT NULL,
    tool_name   TEXT,
    input_json  TEXT,
    output_json TEXT,
    model       TEXT,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    latency_ms  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (run_id, step_no)
);
CREATE INDEX IF NOT EXISTS idx_trace_created ON trace_step(created_at);

CREATE TABLE IF NOT EXISTS app_user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('viewer','admin'))
);

CREATE TABLE IF NOT EXISTS session (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_id INTEGER NOT NULL REFERENCES insight(id)  ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    comment    TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS access_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES app_user(id) ON DELETE SET NULL,
    client_id  TEXT,
    action     TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose    TEXT NOT NULL,
    model      TEXT,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);

CREATE TABLE IF NOT EXISTS llm_cache (
    key        TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

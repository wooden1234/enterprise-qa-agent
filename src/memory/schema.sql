-- 长期记忆。结构参照 fin-harness 的 memory_records / memory_events。
-- 放在 enterprise_qa，用户编号用文本，避免依赖 fin-harness 的 app.users。
CREATE SCHEMA IF NOT EXISTS enterprise_qa;

CREATE TABLE IF NOT EXISTS enterprise_qa.memory_records (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    user_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    value_json JSONB NOT NULL,
    display_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    source_run_id TEXT,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS memory_records_scope_idx
    ON enterprise_qa.memory_records (tenant_id, user_id, memory_type, status);

CREATE UNIQUE INDEX IF NOT EXISTS memory_records_active_key_idx
    ON enterprise_qa.memory_records (tenant_id, user_id, memory_type, memory_key)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS enterprise_qa.memory_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    memory_id TEXT REFERENCES enterprise_qa.memory_records (id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_events_scope_idx
    ON enterprise_qa.memory_events (tenant_id, user_id, created_at);

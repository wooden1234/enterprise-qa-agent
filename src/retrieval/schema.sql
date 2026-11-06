CREATE SCHEMA IF NOT EXISTS enterprise_qa;

CREATE TABLE IF NOT EXISTS enterprise_qa.documents (
    doc_id TEXT PRIMARY KEY,
    document_name TEXT NOT NULL,
    source TEXT NOT NULL,
    version_date TEXT NOT NULL,
    metadata JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprise_qa.policy_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES enterprise_qa.documents (doc_id),
    text TEXT NOT NULL,
    metadata JSONB NOT NULL,
    embedding vector(1536),
    ingested_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS policy_chunks_doc_id_idx
    ON enterprise_qa.policy_chunks (doc_id);

CREATE INDEX IF NOT EXISTS policy_chunks_metadata_idx
    ON enterprise_qa.policy_chunks USING gin (metadata);

CREATE INDEX IF NOT EXISTS policy_chunks_embedding_idx
    ON enterprise_qa.policy_chunks USING hnsw (embedding vector_cosine_ops);

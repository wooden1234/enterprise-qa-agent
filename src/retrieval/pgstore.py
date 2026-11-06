"""把制度切片写入 Postgres。元数据放在 JSONB 字段里，向量放在 pgvector 列。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.retrieval.settings import get_settings
from src.retrieval.store import load_chunk_file, load_vectors

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def database_url():
    return get_settings().PGVECTOR_DATABASE_URL


def connect():
    url = database_url()
    if not url:
        return None
    import psycopg2

    return psycopg2.connect(url)


def ensure_schema(conn):
    with conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for statement in SCHEMA_PATH.read_text(encoding="utf-8").split(";"):
            sql = statement.strip()
            if not sql:
                continue
            try:
                cursor.execute("SAVEPOINT schema_step")
                cursor.execute(sql)
                cursor.execute("RELEASE SAVEPOINT schema_step")
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT schema_step")
                if "hnsw" not in sql.lower():
                    raise
    conn.commit()


def upsert_chunks(chunks, vectors):
    import psycopg2
    from psycopg2.extras import Json, execute_values

    documents = {}
    for chunk in chunks:
        metadata = chunk["metadata"]
        documents[metadata["doc_id"]] = metadata
    conn = connect()
    if conn is None:
        raise RuntimeError("未配置 PGVECTOR_DATABASE_URL")
    try:
        ensure_schema(conn)
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE enterprise_qa.policy_chunks, enterprise_qa.documents")
            execute_values(
                cursor,
                """
                INSERT INTO enterprise_qa.documents
                    (doc_id, document_name, source, version_date, metadata, ingested_at)
                VALUES %s
                """,
                [
                    (
                        item["doc_id"],
                        item["document_name"],
                        item.get("source") or "",
                        item.get("version_date") or "",
                        Json(_document_metadata(item)),
                        item.get("ingested_at"),
                    )
                    for item in documents.values()
                ],
            )
            execute_values(
                cursor,
                """
                INSERT INTO enterprise_qa.policy_chunks
                    (chunk_id, doc_id, text, metadata, embedding, ingested_at)
                VALUES %s
                """,
                [
                    (
                        chunk["chunk_id"],
                        chunk["metadata"]["doc_id"],
                        chunk["text"],
                        Json(chunk["metadata"]),
                        _vector_literal(vectors.get(chunk["chunk_id"])),
                        chunk["metadata"].get("ingested_at"),
                    )
                    for chunk in chunks
                ],
                template="(%s, %s, %s, %s, %s::vector, %s)",
            )
        conn.commit()
        return summarize(conn)
    finally:
        conn.close()


def fetch_chunks():
    """配置了数据库且表里有切片时返回记录，否则返回 None，调用方继续读本地文件。"""
    if not database_url():
        return None
    try:
        conn = connect()
    except Exception:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT chunk_id, text, metadata
                FROM enterprise_qa.policy_chunks
                ORDER BY chunk_id
                """
            )
            rows = cursor.fetchall()
    except Exception:
        return None
    finally:
        conn.close()
    if not rows:
        return None
    return [
        {"chunk_id": chunk_id, "text": text, "metadata": metadata if isinstance(metadata, dict) else json.loads(metadata)}
        for chunk_id, text, metadata in rows
    ]


def search_by_vector(query_vector, top_k, min_score):
    if not database_url():
        return None
    try:
        conn = connect()
    except Exception:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT chunk_id, text, metadata, 1 - (embedding <=> %s::vector) AS score
                FROM enterprise_qa.policy_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (_vector_literal(query_vector), _vector_literal(query_vector), top_k),
            )
            rows = cursor.fetchall()
    except Exception:
        return None
    finally:
        conn.close()
    hits = []
    for chunk_id, text, metadata, score in rows:
        if score < min_score:
            continue
        hits.append(
            {
                "chunk_id": chunk_id,
                "text": text,
                "metadata": metadata if isinstance(metadata, dict) else json.loads(metadata),
                "score": float(score),
            }
        )
    return hits


def summarize(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM enterprise_qa.documents) AS documents,
                count(*) AS chunks,
                count(embedding) AS embeddings,
                count(DISTINCT metadata->>'document_name') AS document_names,
                min(ingested_at) AS ingested_at
            FROM enterprise_qa.policy_chunks
            """
        )
        row = cursor.fetchone()
    return {
        "documents": row[0],
        "chunks": row[1],
        "embeddings": row[2],
        "document_names": row[3],
        "ingested_at": row[4].isoformat() if row[4] is not None else "",
    }


def _document_metadata(metadata):
    return {
        "doc_id": metadata.get("doc_id") or "",
        "document_name": metadata.get("document_name") or "",
        "source": metadata.get("source") or "",
        "version_date": metadata.get("version_date") or "",
        "category": metadata.get("category") or "policy",
        "ingested_at": metadata.get("ingested_at") or "",
    }


def _vector_literal(vector):
    if not vector:
        return None
    return "[" + ",".join("%.8f" % value for value in vector) + "]"


def main():
    chunks = load_chunk_file()
    if not chunks:
        print("chunks_missing", file=sys.stderr)
        return 2
    vectors = load_vectors().get("vectors") or {}
    try:
        summary = upsert_chunks(chunks, vectors)
    except Exception as exc:
        print("pg_failed %s" % exc, file=sys.stderr)
        return 2
    print(
        "pg schema=enterprise_qa documents=%s chunks=%s embeddings=%s ingested_at=%s"
        % (summary["documents"], summary["chunks"], summary["embeddings"], summary["ingested_at"])
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

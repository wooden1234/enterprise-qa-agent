"""读写 enterprise_qa 里的长期偏好。数据库不可用时读取返回空偏好。"""

from __future__ import annotations

import json
from pathlib import Path

from src.harness.session.types import new_id
from src.memory.preferences import PREFERENCE_KEYS

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def load_preferences(user_id="default", tenant_id="default"):
    """读取该用户仍有效的 preference。失败时不打断问答。"""
    conn = _connect()
    if conn is None:
        return {}
    try:
        _ensure_schema(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT memory_key, value_json
                FROM enterprise_qa.memory_records
                WHERE tenant_id = %s
                  AND user_id = %s
                  AND memory_type = 'preference'
                  AND status = 'active'
                  AND deleted_at IS NULL
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                (_scope(tenant_id), _scope(user_id)),
            )
            rows = cursor.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        return {}
    finally:
        conn.close()
    preferences = {}
    for key, value in rows:
        if key not in PREFERENCE_KEYS:
            continue
        parsed = _parse_value(value)
        if parsed is not None:
            preferences[key] = parsed
    return preferences


def save_preference(user_id, memory_key, value, tenant_id="default", run_id=""):
    """写入或更新一条长期偏好，并记一条事件。"""
    key = str(memory_key or "").strip()
    choices = PREFERENCE_KEYS.get(key)
    if choices is None:
        raise ValueError("不支持的长期偏好：" + key)
    stored = str(value or "").strip()
    if stored not in choices:
        raise ValueError("%s 只能是 %s" % (key, "、".join(choices)))
    conn = _connect()
    if conn is None:
        raise RuntimeError("未配置 PGVECTOR_DATABASE_URL")
    try:
        _ensure_schema(conn)
        scope_tenant = _scope(tenant_id)
        scope_user = _scope(user_id)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, version
                FROM enterprise_qa.memory_records
                WHERE tenant_id = %s AND user_id = %s
                  AND memory_type = 'preference' AND memory_key = %s AND status = 'active'
                """,
                (scope_tenant, scope_user, key),
            )
            current = cursor.fetchone()
            payload = json.dumps(stored)
            display = "%s=%s" % (key, stored)
            if current is None:
                memory_id = new_id()
                cursor.execute(
                    """
                    INSERT INTO enterprise_qa.memory_records
                        (id, tenant_id, user_id, memory_type, memory_key, value_json, display_text, source_run_id)
                    VALUES (%s, %s, %s, 'preference', %s, %s::jsonb, %s, %s)
                    """,
                    (memory_id, scope_tenant, scope_user, key, payload, display, run_id or None),
                )
                event_type = "created"
                version = 1
            else:
                memory_id, version = current[0], int(current[1]) + 1
                cursor.execute(
                    """
                    UPDATE enterprise_qa.memory_records
                    SET value_json = %s::jsonb,
                        display_text = %s,
                        version = %s,
                        source_run_id = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (payload, display, version, run_id or None, memory_id),
                )
                event_type = "updated"
            cursor.execute(
                """
                INSERT INTO enterprise_qa.memory_events
                    (id, tenant_id, user_id, memory_id, event_type, payload_json)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    new_id(),
                    scope_tenant,
                    scope_user,
                    memory_id,
                    event_type,
                    json.dumps({"memory_key": key, "value": stored, "version": version}),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"memory_key": key, "value": stored, "user_id": _scope(user_id)}


def _connect():
    from src.retrieval.pgstore import connect

    return connect()


def _ensure_schema(conn):
    with conn.cursor() as cursor:
        for statement in SCHEMA_PATH.read_text(encoding="utf-8").split(";"):
            sql = statement.strip()
            if sql:
                cursor.execute(sql)


def _scope(value):
    text = str(value or "").strip()
    return text or "default"


def _parse_value(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    if isinstance(value, (str, int, float)):
        return str(value)
    return None

"""db 层测试：schema 结构、字段分层的物理保证、schema_version 校验。

对应设计 §2 数据模型、验收 #3（分层存储）、#4（守恒断言的结构前提）。
"""
import sqlite3

import pytest

from alpha_platform import db


def test_建库后四张表齐备(tmp_path):
    conn = db.connect(tmp_path / "inventory.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"alpha", "alpha_state", "sync_slice", "meta"} <= tables


def test_funnel_status_非空由_schema_强制(tmp_path):
    """D10：funnel_status 恒非空是消除 `NULL NOT IN` 静默排除的根本手段。"""
    conn = db.connect(tmp_path / "inventory.db")
    conn.execute(
        "INSERT INTO alpha(alpha_id, stage, date_created, expression, raw_json, fetched_at)"
        " VALUES ('A1','IS','2026-01-01T00:00:00Z','x','{}','2026-08-15T00:00:00Z')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO alpha_state(alpha_id, funnel_status) VALUES ('A1', NULL)")


def test_status_source_默认为_sync(tmp_path):
    conn = db.connect(tmp_path / "inventory.db")
    _insert_alpha(conn, "A1")
    conn.execute("INSERT INTO alpha_state(alpha_id, funnel_status) VALUES ('A1','已回测')")
    row = conn.execute("SELECT status_source, is_pending_flag FROM alpha_state").fetchone()
    assert row["status_source"] == "sync"
    assert row["is_pending_flag"] == 0


def test_初始态只创建不覆盖(tmp_path):
    """D10/§4.2：ON CONFLICT DO NOTHING —— 「不覆盖」才是字段分层要保护的，「不创建」不是。"""
    conn = db.connect(tmp_path / "inventory.db")
    _insert_alpha(conn, "A1")
    db.ensure_state(conn, "A1", db.BACKTESTED)
    conn.execute("UPDATE alpha_state SET funnel_status='待确认' WHERE alpha_id='A1'")

    db.ensure_state(conn, "A1", db.BACKTESTED)  # 再次同步

    assert conn.execute("SELECT funnel_status FROM alpha_state").fetchone()[0] == "待确认"


def test_schema_version_写入并在不匹配时拒绝打开(tmp_path):
    path = tmp_path / "inventory.db"
    conn = db.connect(path)
    assert db.get_meta(conn, "schema_version") == db.SCHEMA_VERSION
    db.set_meta(conn, "schema_version", "999")
    conn.close()

    with pytest.raises(db.SchemaVersionError):
        db.connect(path)


def test_七态常量与设计_3_1_一致():
    assert db.FUNNEL_STATUSES == (
        "已回测",
        "可提交候选",
        "改造候选",
        "淘汰候选",
        "待确认",
        "已提交",
        "提交失败",
    )
    assert db.PROTECTED_STATUSES == ("待确认", "已提交", "提交失败")


def _insert_alpha(conn, alpha_id):
    conn.execute(
        "INSERT INTO alpha(alpha_id, stage, date_created, expression, raw_json, fetched_at)"
        " VALUES (?,'IS','2026-01-01T00:00:00Z','x','{}','2026-08-15T00:00:00Z')",
        (alpha_id,),
    )

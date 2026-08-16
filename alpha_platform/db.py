"""连接管理、schema 建表、schema_version 校验（设计 §2）。

字段分层由 schema 强制而非代码纪律：同步只写 `alpha`，派生数据在 `alpha_state`。
唯一例外是初始态创建（`ensure_state`），只创建不覆盖——见设计 §4.2。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = "1"

# 漏斗七态（PRD §3.1）
BACKTESTED = "已回测"
SUBMITTABLE = "可提交候选"
REWORK = "改造候选"
DISCARD = "淘汰候选"
PENDING_CONFIRM = "待确认"
SUBMITTED = "已提交"
SUBMIT_FAILED = "提交失败"

FUNNEL_STATUSES = (
    BACKTESTED,
    SUBMITTABLE,
    REWORK,
    DISCARD,
    PENDING_CONFIRM,
    SUBMITTED,
    SUBMIT_FAILED,
)

# 分流与预判都不得改写的状态（设计 §4.3 适用域、§4.4 --reset 守卫）
PROTECTED_STATUSES = (PENDING_CONFIRM, SUBMITTED, SUBMIT_FAILED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alpha (
    alpha_id       TEXT PRIMARY KEY,
    stage          TEXT NOT NULL,
    date_created   TEXT NOT NULL,
    date_submitted TEXT,
    expression     TEXT NOT NULL,
    raw_json       TEXT NOT NULL,
    fetched_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alpha_date_created ON alpha(date_created);

CREATE TABLE IF NOT EXISTS alpha_state (
    alpha_id               TEXT PRIMARY KEY REFERENCES alpha(alpha_id),
    funnel_status          TEXT NOT NULL,
    status_source          TEXT NOT NULL DEFAULT 'sync',
    is_pending_flag        INTEGER NOT NULL DEFAULT 0,
    classified_at          TEXT,
    classify_threshold     REAL,
    classify_rule_version  TEXT,
    classify_reason_json   TEXT,
    prediction_result      TEXT,
    prediction_reason_json TEXT,
    predicted_at           TEXT,
    confirm_fingerprint    TEXT,
    confirmed_at           TEXT,
    submitted_at           TEXT,
    submit_result          TEXT,
    submit_error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_state_funnel ON alpha_state(funnel_status);

CREATE TABLE IF NOT EXISTS sync_slice (
    stage          TEXT NOT NULL,
    slice_from     TEXT NOT NULL,
    slice_to       TEXT NOT NULL,
    reported_count INTEGER NOT NULL,
    fetched_count  INTEGER NOT NULL,
    status         TEXT NOT NULL,
    completed_at   TEXT,
    PRIMARY KEY (stage, slice_from, slice_to)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SchemaVersionError(RuntimeError):
    """库文件的 schema 版本与本程序不匹配（设计 §6.1）。"""


def connect(path: str | Path) -> sqlite3.Connection:
    """打开（必要时创建）库文件，建表并校验 schema 版本。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None 即 autocommit：每条 execute 立即落盘。
    # ★ 这是 submit.py 崩溃安全性的隐式前提——`in_flight` 意向标记必须在
    # POST 之前真正落到磁盘，否则进程被杀时它会随未提交事务一起消失，N8 的
    # 整条恢复路径就失效了。若日后要给本连接加 isolation_level，必须同时给
    # submit.py 的意向标记补显式提交。需要批量原子性的地方各自显式 BEGIN
    # （见 sync.py::_transaction、classify.py::run）。
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)

    version = get_meta(conn, "schema_version")
    if version is None:
        set_meta(conn, "schema_version", SCHEMA_VERSION)
    elif version != SCHEMA_VERSION:
        conn.close()
        raise SchemaVersionError(
            f"库文件 schema 版本为 {version}，本程序需要 {SCHEMA_VERSION}；"
            f"请迁移或删除 {path} 后重新同步"
        )
    return conn


def ensure_state(conn: sqlite3.Connection, alpha_id: str, funnel_status: str) -> None:
    """创建初始派生状态；行已存在时**不做任何改动**（设计 §4.2 D10）。"""
    conn.execute(
        "INSERT INTO alpha_state (alpha_id, funnel_status, status_source)"
        " VALUES (?, ?, 'sync') ON CONFLICT(alpha_id) DO NOTHING",
        (alpha_id, funnel_status),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )

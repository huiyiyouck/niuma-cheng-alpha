"""分流引擎（PRD #4 / #5，设计 §3.2 规则 + §4.3 适用域与写回）。

核心 `classify_checks` 是纯函数、不碰 IO——这是 PRD #5「注入不同 limit 断言
分流结果变化」能被单测覆盖的前提。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import db

RULE_VERSION = "v1"

GATE_RESULTS = ("PASS", "FAIL")


@dataclass(frozen=True)
class ClassifyResult:
    funnel_status: str
    reason: dict


def classify_checks(checks: list[dict], threshold: float) -> ClassifyResult:
    """输入 is.checks[] 与改造阈值，输出状态与理由。无 IO、无全局状态、可重复调用。"""
    gate_fails: list[dict] = []
    gate_passes: list[str] = []
    non_gate: list[dict] = []

    for check in checks or []:
        name = check.get("name")
        result = check.get("result")
        if result not in GATE_RESULTS:
            # WARNING / ERROR / PENDING 一律非门槛：不参与判定，但必须留痕
            non_gate.append({"name": name, "result": result})
        elif result == "PASS":
            gate_passes.append(name)
        else:
            gate_fails.append(_fail_detail(name, check.get("value"), check.get("limit")))

    if not gate_fails:
        verdict = db.SUBMITTABLE
    elif any(f["quantifiable"] and f["gap"] > threshold for f in gate_fails):
        verdict = db.DISCARD
    else:
        # 含不可量化 FAIL 时保守归改造候选
        verdict = db.REWORK

    return ClassifyResult(
        funnel_status=verdict,
        reason={
            "rule_version": RULE_VERSION,
            "threshold": threshold,
            "verdict": verdict,
            "gate_fails": gate_fails,
            "gate_passes": gate_passes,
            "non_gate": non_gate,
        },
    )


def _fail_detail(name: str, value, limit) -> dict:
    """gap = |value − limit| / |limit|；缺省或 limit==0 时不可量化。"""
    quantifiable = isinstance(value, (int, float)) and isinstance(limit, (int, float)) and limit != 0
    gap = abs(value - limit) / abs(limit) if quantifiable else None
    return {"name": name, "value": value, "limit": limit, "gap": gap, "quantifiable": quantifiable}


def run(conn: sqlite3.Connection, *, threshold: float = 0.3, scope: str = "all") -> dict[str, int]:
    """对适用域重算分流，返回各状态计数。

    适用域只排除保护态——**不在 SQL 里判断可空的 prediction_result**（D16）：
    `NULL = 'fail'` 求值为 NULL 会让「从未预判的改造候选」被 WHERE 静默丢弃。
    fail 判断放在下面的写回逻辑里做（Python 二值比较，无三值陷阱）。
    """
    placeholders = ",".join("?" * len(db.PROTECTED_STATUSES))
    sql = (
        "SELECT a.alpha_id, a.raw_json, s.prediction_result, s.status_source"
        " FROM alpha a JOIN alpha_state s ON s.alpha_id = a.alpha_id"
        f" WHERE s.funnel_status NOT IN ({placeholders})"
    )
    params = list(db.PROTECTED_STATUSES)
    if scope == "unclassified":
        sql += " AND s.classified_at IS NULL"

    now = datetime.now(timezone.utc).isoformat()
    counts: dict[str, int] = {}

    # A20：整体包一个事务——中途失败若留下「部分新阈值、部分旧阈值」的混合态，
    # report 会给出误导性的混合结果。（precheck 的逐条 autocommit 是有意为之，
    # 那里要的是断点续跑，不要一并改。）
    conn.execute("BEGIN")
    try:
        counts = _classify_rows(conn, conn.execute(sql, params).fetchall(), threshold, now)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return counts


def _classify_rows(conn, rows, threshold: float, now: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        checks = (json.loads(row["raw_json"]).get("is") or {}).get("checks") or []
        result = classify_checks(checks, threshold)

        # D14/D17：预判判死的记录锁定状态与来源，但理由照常刷新
        locked = row["prediction_result"] == "fail"
        funnel_status = db.REWORK if locked else result.funnel_status
        status_source = "prediction" if locked else "classify"

        conn.execute(
            "UPDATE alpha_state SET funnel_status = ?, status_source = ?, classified_at = ?,"
            " classify_threshold = ?, classify_rule_version = ?, classify_reason_json = ?"
            " WHERE alpha_id = ?",
            (
                funnel_status,
                status_source,
                now,
                threshold,
                RULE_VERSION,
                json.dumps(result.reason, ensure_ascii=False),
                row["alpha_id"],
            ),
        )
        counts[funnel_status] = counts.get(funnel_status, 0) + 1

    return counts


def conservation_holds(conn: sqlite3.Connection) -> bool:
    """守恒断言（D20）：alpha 行数 == alpha_state 行数 == 七态计数之和，恒成立。"""
    alphas = conn.execute("SELECT COUNT(*) FROM alpha").fetchone()[0]
    states = conn.execute("SELECT COUNT(*) FROM alpha_state").fetchone()[0]
    placeholders = ",".join("?" * len(db.FUNNEL_STATUSES))
    by_status = conn.execute(
        f"SELECT COUNT(*) FROM alpha_state WHERE funnel_status IN ({placeholders})",
        db.FUNNEL_STATUSES,
    ).fetchone()[0]
    return alphas == states == by_status

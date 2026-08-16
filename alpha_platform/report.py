"""漏斗报告（PRD #7 / #3，设计 §4.5）。只读，纯 SQL 聚合 + Python 展开 JSON 理由。"""
from __future__ import annotations

import json
import sqlite3

from . import db


def build(conn: sqlite3.Connection) -> dict:
    return {
        "status_counts": _status_counts(conn),
        "rework_by_source": _rework_by_source(conn),
        "fail_top": _fail_top(conn),
        "undetermined_gate_candidates": _undetermined_gate_candidates(conn),
        # Q7：限定「仍是可提交候选」——否则会提示 Owner 去重试一条已不是候选的 Alpha
        "pending_count": conn.execute(
            "SELECT COUNT(*) FROM alpha_state WHERE is_pending_flag = 1 AND funnel_status = ?",
            (db.SUBMITTABLE,),
        ).fetchone()[0],
    }


def _status_counts(conn) -> dict[str, int]:
    rows = conn.execute(
        "SELECT funnel_status, COUNT(*) AS n FROM alpha_state GROUP BY funnel_status"
    ).fetchall()
    counts = {row["funnel_status"]: row["n"] for row in rows}
    # 七态全列，计数为 0 也保留（A21）：Owner 要能分辨「提交失败 0 条」与
    # 「这个状态压根没出现过」——漏斗视图的价值就在于分级完整。
    # 「未回测」不在 FUNNEL_STATUSES 内，天然被排除（v0.3 组装端接入时再新增）。
    return {status: counts.get(status, 0) for status in db.FUNNEL_STATUSES}


def _rework_by_source(conn) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status_source, COUNT(*) AS n FROM alpha_state WHERE funnel_status = ?"
        " GROUP BY status_source",
        (db.REWORK,),
    ).fetchall()
    return {row["status_source"]: row["n"] for row in rows}


def _fail_top(conn) -> list[dict]:
    """从 classify_reason_json.gate_fails 展开，按 check 名聚合次数与平均 gap。"""
    tally: dict[str, list[float]] = {}
    for row in conn.execute(
        "SELECT classify_reason_json FROM alpha_state WHERE classify_reason_json IS NOT NULL"
    ):
        for fail in json.loads(row["classify_reason_json"]).get("gate_fails", []):
            tally.setdefault(fail["name"], []).append(fail.get("gap"))

    result = []
    for name, gaps in tally.items():
        measured = [g for g in gaps if isinstance(g, (int, float))]
        result.append({
            "name": name,
            "count": len(gaps),
            "avg_gap": sum(measured) / len(measured) if measured else None,
        })
    return sorted(result, key=lambda r: r["count"], reverse=True)


def _undetermined_gate_candidates(conn) -> int:
    """A12：`non_gate` 含 ERROR / PENDING 的「可提交候选」条数。

    CLUSTER_TEST 全样本为 ERROR——若它日后被证实是硬门槛，当前分流整体偏乐观，
    提交机会稀缺，这个数字必须对 Owner 可见。
    """
    total = 0
    for row in conn.execute(
        "SELECT classify_reason_json FROM alpha_state"
        " WHERE funnel_status = ? AND classify_reason_json IS NOT NULL",
        (db.SUBMITTABLE,),
    ):
        non_gate = json.loads(row["classify_reason_json"]).get("non_gate", [])
        if any(item.get("result") in ("ERROR", "PENDING") for item in non_gate):
            total += 1
    return total


def list_by_status(conn: sqlite3.Connection, status: str) -> list[dict]:
    """承接 PRD #3「可按漏斗状态查询」在 CLI 层的落点，也是 --reset 取 ID 的来源。"""
    rows = conn.execute(
        "SELECT a.alpha_id, a.expression, s.status_source, s.classify_reason_json,"
        " s.prediction_result FROM alpha a JOIN alpha_state s ON s.alpha_id = a.alpha_id"
        " WHERE s.funnel_status = ? ORDER BY a.alpha_id",
        (status,),
    ).fetchall()
    return [
        {
            "alpha_id": row["alpha_id"],
            "expression": row["expression"],
            "status_source": row["status_source"],
            "prediction_result": row["prediction_result"],
            "reason": _reason_digest(row["classify_reason_json"]),
        }
        for row in rows
    ]


def _reason_digest(raw: str | None) -> str:
    if not raw:
        return ""
    fails = json.loads(raw).get("gate_fails", [])
    return "、".join(
        f"{f['name']}(gap={f['gap']:.3f})" if isinstance(f.get("gap"), (int, float)) else f"{f['name']}(不可量化)"
        for f in fails
    )


def render(data: dict, *, fmt: str = "text") -> str:
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)

    lines = ["漏斗各级数量："]
    for status, count in data["status_counts"].items():
        lines.append(f"  {status:<12}{count}")
        if status == db.REWORK and data["rework_by_source"]:
            for source, n in sorted(data["rework_by_source"].items()):
                label = "因 checks FAIL" if source == "classify" else "因相关性超阈"
                lines.append(f"      └ {label}（{source}）{n}")

    lines.append("")
    lines.append("FAIL 卡点分布 TOP：")
    for row in data["fail_top"][:10]:
        avg = f"{row['avg_gap']:.3f}" if row["avg_gap"] is not None else "—"
        lines.append(f"  {row['name']:<28}{row['count']:>6}    平均 gap {avg}")

    lines.append("")
    lines.append(f"携带未判定门槛类 check（ERROR/PENDING）的可提交候选：{data['undetermined_gate_candidates']}")
    lines.append(f"预判待定：{data['pending_count']}（可用 `precheck --retry-pending` 重试）")
    return "\n".join(lines)


def render_list(rows: list[dict]) -> str:
    if not rows:
        return "（无记录）"
    lines = [f"{'alpha_id':<16}{'来源':<12}{'表达式'}"]
    for row in rows:
        lines.append(f"{row['alpha_id']:<16}{row['status_source']:<12}{row['expression']}")
        if row["reason"]:
            lines.append(f"    卡点：{row['reason']}")
    return "\n".join(lines)

"""提交前预判：两阶段短路（PRD #6，设计 §4.4）。

成本是本流程的核心约束：相关性接口最坏约 80 秒等待/条。self 超阈即可判死
（self-corr > 阈值则 prod-corr 必然超阈），最坏调用次数因此减半。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import db
from .config import Config

# 允许 --reset 点名的状态：可提交候选，或「因相关性判死」的改造候选（D23）。
# 因 checks FAIL 归入的改造候选不在其列——它重新预判若通过会进提交清单。
_RESETTABLE = (
    f"funnel_status = '{db.SUBMITTABLE}'"
    f" OR (funnel_status = '{db.REWORK}' AND status_source = 'prediction')"
)


class ResetGuardError(RuntimeError):
    """--reset 点名了不该被重置的记录——明确报错，不静默跳过（D18）。"""


def run(client, conn: sqlite3.Connection, *, config: Config, batch_size: int | None = None,
        limit: int | None = None, reset: list[str] | None = None,
        retry_pending: bool = False, progress=None) -> dict[str, int]:
    """对候选集分批执行两阶段预判，每条结论立即落库并提交事务。

    分批（PRD #6「执行须分批、单批规模可配」）：批间是天然的节流点，也是 Owner
    在这个最坏以小时计的长任务上唯一的进度抓手（设计 §5）。每条结论仍逐条落库，
    断点粒度是「条」而不是「批」——中断后重跑不会退回整批重来。
    """
    if reset:
        _guard_reset(conn, reset)

    rows = _candidates(conn, reset=reset, retry_pending=retry_pending, limit=limit)
    threshold = {"value": config.correlation_threshold, "source": config.correlation_threshold_source}
    size = batch_size or config.batch_size
    counts: dict[str, int] = {}
    done = 0

    for start in range(0, len(rows), size):
        for row in rows[start : start + size]:
            verdict, reason = _predict(client, row["alpha_id"], config.correlation_threshold, threshold)
            _write_back(conn, row["alpha_id"], verdict, reason)
            counts[verdict] = counts.get(verdict, 0) + 1
            done += 1
        if progress:
            progress(f"预判进度 {done}/{len(rows)}（本批 {min(size, len(rows) - start)} 条）")

    return counts


def _predict(client, alpha_id: str, threshold: float, threshold_meta: dict) -> tuple[str, dict]:
    self_result = client.get_self_correlation(alpha_id)
    if self_result.max_correlation is None:
        return "pending", _reason("pending", "self", self_result, None, threshold_meta, False)
    if self_result.max_correlation >= threshold:
        # 短路：不再调用 prod 接口
        return "fail", _reason("fail", "self", self_result, None, threshold_meta, True)

    prod_result = client.get_prod_correlation(alpha_id)
    if prod_result.max_correlation is None:
        return "pending", _reason("pending", "prod", self_result, prod_result, threshold_meta, False)
    if prod_result.max_correlation >= threshold:
        return "fail", _reason("fail", "prod", self_result, prod_result, threshold_meta, False)
    return "pass", _reason("pass", "prod", self_result, prod_result, threshold_meta, False)


def _reason(verdict, stage_reached, self_result, prod_result, threshold_meta, short_circuited) -> dict:
    return {
        "verdict": verdict,
        "stage_reached": stage_reached,
        "self_correlation": self_result.max_correlation,
        "prod_correlation": prod_result.max_correlation if prod_result else None,
        "threshold": threshold_meta,
        "attempts": self_result.attempts + (prod_result.attempts if prod_result else 0),
        "short_circuited": short_circuited,
    }


def _write_back(conn, alpha_id: str, verdict: str, reason: dict) -> None:
    """立即写库并提交事务——任意时刻中断，已完成部分不丢。"""
    if verdict == "pass":
        funnel_status, pending_flag = db.PENDING_CONFIRM, 0
    elif verdict == "fail":
        funnel_status, pending_flag = db.REWORK, 0
    else:
        # 待定不是独立状态：保持「可提交候选」加标注（PRD §3.1）
        funnel_status, pending_flag = db.SUBMITTABLE, 1

    conn.execute(
        "UPDATE alpha_state SET prediction_result=?, prediction_reason_json=?, predicted_at=?,"
        " funnel_status=?, status_source='prediction', is_pending_flag=? WHERE alpha_id=?",
        (
            verdict,
            json.dumps(reason, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
            funnel_status,
            pending_flag,
            alpha_id,
        ),
    )


def _candidates(conn, *, reset, retry_pending, limit):
    if reset:
        placeholders = ",".join("?" * len(reset))
        sql = f"SELECT alpha_id FROM alpha_state WHERE alpha_id IN ({placeholders})"
        return conn.execute(sql, reset).fetchall()

    # 常规候选集：可提交候选且无结论；--retry-pending 时把待定一并纳入
    sql = (
        f"SELECT alpha_id FROM alpha_state WHERE funnel_status = '{db.SUBMITTABLE}'"
        "   AND (prediction_result IS NULL"
        + ("    OR prediction_result = 'pending'" if retry_pending else "")
        + ")"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def _guard_reset(conn, reset: list[str]) -> None:
    placeholders = ",".join("?" * len(reset))
    rows = conn.execute(
        f"SELECT alpha_id, funnel_status, status_source FROM alpha_state"
        f" WHERE alpha_id IN ({placeholders}) AND NOT ({_RESETTABLE})",
        reset,
    ).fetchall()
    if rows:
        detail = "、".join(f"{r['alpha_id']}（{r['funnel_status']}）" for r in rows)
        raise ResetGuardError(
            f"以下记录不可重置预判：{detail}。"
            f" 仅「{db.SUBMITTABLE}」与「因相关性判死的{db.REWORK}」可重置"
        )

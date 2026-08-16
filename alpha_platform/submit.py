"""提交（PRD #8，设计 §4.6）—— 唯一不可逆动作。

三重兜底：dry-run 零调用 / 指纹绑定确认 / 快照落盘。
加上 `in_flight` 意向标记与 `--reconcile` 恢复路径，覆盖「POST 成功、写库前
进程死亡」这个窗口——该窗口里不猜测、不自动重提。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import db

IN_FLIGHT = "in_flight"


class FingerprintMismatch(RuntimeError):
    """清单内容已变，确认失效——退出码 4（安全语义：要人重新确认）。"""


class InFlightPending(RuntimeError):
    """存在待核对的 in_flight 记录——退出码 6，先跑 `submit --reconcile`。"""


@dataclass
class DryRunResult:
    items: list[dict]
    fingerprint: str


@dataclass
class SubmitReport:
    succeeded: int = 0
    failed: int = 0
    snapshot_path: Path | None = None


@dataclass
class ReconcileReport:
    resolved_submitted: int = 0
    resolved_reverted: int = 0
    unresolved: int = 0
    details: list = field(default_factory=list)


# --- dry-run ---------------------------------------------------------------


def dry_run(conn: sqlite3.Connection) -> DryRunResult:
    """清单 = 当前处于「待确认」态的全部记录（PRD D8 口径）。提交接口零调用。"""
    items = _pending_list(conn)
    return DryRunResult(items=items, fingerprint=_fingerprint(items))


def _pending_list(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT a.alpha_id, a.expression, s.prediction_result FROM alpha a"
        " JOIN alpha_state s ON s.alpha_id = a.alpha_id"
        " WHERE s.funnel_status = ? ORDER BY a.alpha_id",
        (db.PENDING_CONFIRM,),
    ).fetchall()
    return [
        {"alpha_id": r["alpha_id"], "expression": r["expression"],
         "prediction_result": r["prediction_result"]}
        for r in rows
    ]


def _fingerprint(items: list[dict]) -> str:
    """覆盖 alpha_id 与 prediction_result：增删条目或结论变化，指纹即变。"""
    payload = "\n".join(f"{i['alpha_id']}:{i['prediction_result']}" for i in items)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- confirm ---------------------------------------------------------------


def confirm(client, conn: sqlite3.Connection, *, fingerprint: str,
            snapshot_dir: Path | str) -> SubmitReport:
    current = dry_run(conn)
    if fingerprint != current.fingerprint:
        raise FingerprintMismatch(
            f"清单内容已变，确认失效：期望 {current.fingerprint[:8]}…，收到 {fingerprint[:8]}…；"
            f" 请重新跑 `submit --dry-run` 核对后确认"
        )

    # ⓪ 前置检查：不确定的状态下不碰不可逆动作
    stuck = conn.execute(
        "SELECT COUNT(*) FROM alpha_state WHERE submit_result = ?", (IN_FLIGHT,)
    ).fetchone()[0]
    if stuck:
        raise InFlightPending(
            f"存在 {stuck} 条待核对记录（{IN_FLIGHT}），请先跑 `submit --reconcile`"
        )

    # ① 意向快照先落盘——证据写不下就不执行不可逆动作（N12）
    snapshot_path = _write_intent_snapshot(snapshot_dir, current)

    report = SubmitReport(snapshot_path=snapshot_path)
    results: dict[str, dict] = {}
    now = _now()

    for item in current.items:
        alpha_id = item["alpha_id"]
        # a. 意向标记先落库，再 POST（N8）
        conn.execute(
            "UPDATE alpha_state SET submit_result=?, confirm_fingerprint=?, confirmed_at=?"
            " WHERE alpha_id=?",
            (IN_FLIGHT, current.fingerprint, now, alpha_id),
        )
        outcome = client.submit_alpha(alpha_id)   # b.
        # c. 回写结果
        if outcome.ok:
            conn.execute(
                "UPDATE alpha_state SET funnel_status=?, status_source='submit',"
                " submit_result='success', submitted_at=?, submit_error=NULL WHERE alpha_id=?",
                (db.SUBMITTED, _now(), alpha_id),
            )
            report.succeeded += 1
            results[alpha_id] = {"result": "success", "error": None}
        else:
            conn.execute(
                "UPDATE alpha_state SET funnel_status=?, status_source='submit',"
                " submit_result='failed', submit_error=? WHERE alpha_id=?",
                (db.SUBMIT_FAILED, outcome.error, alpha_id),
            )
            report.failed += 1
            results[alpha_id] = {"result": "failed", "error": outcome.error}

    _patch_snapshot(snapshot_path, results)
    return report


def _write_intent_snapshot(snapshot_dir: Path | str, current: DryRunResult) -> Path:
    snapshot_dir = Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = snapshot_dir / f"{stamp}-{current.fingerprint[:8]}.json"
    payload = {
        "fingerprint": current.fingerprint,
        "confirmed_at": _now(),
        "items": [{**item, "result": None, "error": None} for item in current.items],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _patch_snapshot(path: Path, results: dict[str, dict]) -> None:
    """原地补齐逐条结果；文件名由指纹决定、内容单调补全。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["items"]:
        item.update(results.get(item["alpha_id"], {}))
    payload["completed_at"] = _now()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# --- reconcile（恢复路径） -------------------------------------------------


def reconcile(client, conn: sqlite3.Connection, *, snapshot_dir: Path | str) -> ReconcileReport:
    """按平台真实状态收敛 `in_flight`。

    判据取自 `client.get_alpha` 直查——**不经本地库、不经水位**。恢复路径不该
    依赖那条可能已经出问题的常规写入链（D21/N14）。
    """
    report = ReconcileReport()
    rows = conn.execute(
        "SELECT alpha_id, confirm_fingerprint FROM alpha_state WHERE submit_result = ?"
        " ORDER BY alpha_id",
        (IN_FLIGHT,),
    ).fetchall()

    for row in rows:
        alpha_id = row["alpha_id"]
        try:
            detail = client.get_alpha(alpha_id)
        except Exception as exc:                      # 不猜测、不收敛（N15）
            report.unresolved += 1
            report.details.append({"alpha_id": alpha_id, "action": "保持 in_flight", "error": str(exc)})
            continue

        # 详情已在手，零额外请求——顺带让 alpha 表与平台自洽（D24）
        _refresh_alpha(conn, alpha_id, detail)

        if detail.get("stage") == "OS":
            conn.execute(
                "UPDATE alpha_state SET funnel_status=?, status_source='submit',"
                " submit_result='success', submitted_at=?, submit_error=NULL WHERE alpha_id=?",
                (db.SUBMITTED, detail.get("dateSubmitted"), alpha_id),
            )
            report.resolved_submitted += 1
            outcome = {"result": "success", "error": None}
            report.details.append({"alpha_id": alpha_id, "action": "收敛为已提交"})
        else:
            conn.execute(
                # A23：该状态由 reconcile 造成，不是预判的结论
                "UPDATE alpha_state SET funnel_status=?, status_source='submit',"
                " submit_result=NULL, submitted_at=NULL WHERE alpha_id=?",
                (db.PENDING_CONFIRM, alpha_id),
            )
            report.resolved_reverted += 1
            outcome = {"result": "reverted", "error": "提交未达成，已退回待确认"}
            report.details.append({"alpha_id": alpha_id, "action": "退回待确认（提交未达成）"})

        # A14：状态恢复了，证据也要跟着恢复——**每条收敛后立即补齐**（O3 ①），
        # 因为 reconcile 自身也可能中途死亡。
        _patch_snapshot_for(snapshot_dir, row["confirm_fingerprint"], alpha_id, outcome)

    return report


def _patch_snapshot_for(snapshot_dir: Path | str, fingerprint: str | None,
                        alpha_id: str, outcome: dict) -> None:
    """按确认指纹定位该条所属的快照，补齐它的结果字段。

    快照文件名形如 `{时间戳}-{指纹前8位}.json`；同一指纹若有多份（同一清单被确认
    过多次），取时间戳最大的那份——即这条 `in_flight` 实际所属的那次提交。
    """
    if not fingerprint:
        return
    candidates = sorted(Path(snapshot_dir).glob(f"*-{fingerprint[:8]}.json"))
    if not candidates:
        return

    path = candidates[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload["items"]:
        if item["alpha_id"] == alpha_id:
            item.update(outcome)
    payload["reconciled_at"] = _now()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _refresh_alpha(conn, alpha_id: str, detail: dict) -> None:
    conn.execute(
        "UPDATE alpha SET stage=?, date_submitted=?, expression=?, raw_json=?, fetched_at=?"
        " WHERE alpha_id=?",
        (
            detail.get("stage"),
            detail.get("dateSubmitted"),
            (detail.get("regular") or {}).get("code", ""),
            json.dumps(detail, ensure_ascii=False),
            _now(),
            alpha_id,
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

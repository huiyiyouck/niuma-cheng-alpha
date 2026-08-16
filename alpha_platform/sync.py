"""同步：全量时间窗自适应切片 + 增量（PRD #1 / #2 / #3 / #10，设计 §4.1 / §4.2）。

对账的主口径是**窗口级**（每个叶子窗口 fetched == 平台报告的 reported），
它才是可证伪的那一层；另有一条独立于切片路径的全局总量交叉验证（D9）。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import db
from .config import Config

MAX_DEPTH = 64
MIN_WINDOW_SECONDS = 2      # 宽度 ≤ 2s 不再细分（D11：否则 mid-1s 会退回父窗口）
ONE_SECOND = timedelta(seconds=1)

# 初始态映射（PRD §3.1）
_INITIAL_STATUS = {"IS": db.BACKTESTED, "OS": db.SUBMITTED}


@dataclass
class SyncReport:
    stage: str
    fetched: int = 0                     # 本次实际写入/刷新的条数
    local_count: int = 0                 # 同步后本地该 stage 的行数
    total_reported: int | None = None    # 步骤 0 的第三方左值
    reconciled: bool = True              # 窗口级对账结论（主口径）
    mismatched_slices: list = field(default_factory=list)
    offset_ceiling_detected: bool = False
    global_mismatch: bool = False        # 步骤 5：本地行数 vs 第三方左值（只留痕，不判红）


# --- 全量 -----------------------------------------------------------------


def full_sync(client, conn: sqlite3.Connection, *, stage: str, config: Config,
              resume: bool = True, progress=None) -> SyncReport:
    report = SyncReport(stage=stage)

    # 步骤 0：全局总量交叉验证——不带任何时间窗，独立于切片路径（D9）
    report.total_reported = client.list_alphas(stage=stage, limit=1, offset=0).count

    bounds = _root_bounds(client, stage)
    if bounds is None:
        return report

    root_from, root_to = bounds
    _split(client, conn, stage, config, root_from, root_to, 0, report, resume, progress)

    report.local_count = _local_count(conn, stage)
    report.reconciled = not report.mismatched_slices
    db.set_meta(conn, "last_full_sync_at", _now())
    _update_watermark(conn, stage)

    # 步骤 5：全局对账（A17）。左值来自步骤 0 的第三方查询，独立于切片路径——
    # 外扩 1 秒修的是那一个 bug，这条左值修的是「这类 bug 以后还能被发现」。
    # 不判红：total 自身可能被平台计数上限截断，它是诊断信号而非通过条件。
    if report.total_reported != report.local_count:
        report.global_mismatch = True
        db.set_meta(conn, "global_reconcile_mismatch", json.dumps(
            {"stage": stage, "total_reported": report.total_reported,
             "local_count": report.local_count, "at": _now()},
        ))

    # 步骤 7：offset 直连穷尽作为诊断项——断言留痕存在，不断言两数相等
    offset_count = _offset_exhaust_count(client, stage, config)
    if offset_count != report.local_count:
        report.offset_ceiling_detected = True
        db.set_meta(conn, "offset_ceiling_detected", json.dumps(
            {"detected": True, "offset_count": offset_count,
             "slice_count": report.local_count, "at": _now()},
        ))
    return report


def _root_bounds(client, stage) -> tuple[datetime, datetime] | None:
    """根窗口边界外扩 1 秒（D9）。

    平台的 `dateCreated>` / `dateCreated<` 两端都是开区间，若直接取首末条时间戳作边界，
    等于 T_min / T_max 的记录会被根窗口自身排除，一条都进不了库——而 reported_count 与
    fetched_count 同源于这个开区间查询，逐窗口对账查不出来。
    """
    first = client.list_alphas(stage=stage, limit=1, offset=0, order="dateCreated")
    if not first.items:
        return None
    last = client.list_alphas(stage=stage, limit=1, offset=0, order="-dateCreated")
    t_min = _parse(first.items[0]["dateCreated"])
    t_max = _parse(last.items[0]["dateCreated"])
    return t_min - ONE_SECOND, t_max + ONE_SECOND


def _split(client, conn, stage, config, frm, to, depth, report, resume, progress=None) -> None:
    page = client.list_alphas(
        stage=stage, limit=1, offset=0,
        date_created_gt=_fmt(frm), date_created_lt=_fmt(to),
    )
    splittable = (to - frm).total_seconds() > MIN_WINDOW_SECONDS and depth < MAX_DEPTH

    if page.count >= config.split_threshold and splittable:
        # mid 向下取整到秒（D11）
        mid = frm + timedelta(seconds=int((to - frm).total_seconds() // 2))
        _split(client, conn, stage, config, frm, mid, depth + 1, report, resume, progress)
        _split(client, conn, stage, config, mid - ONE_SECOND, to, depth + 1, report, resume, progress)
        return

    unsplittable = page.count >= config.split_threshold      # 超阈值却已无法细分
    _fetch_leaf(client, conn, stage, config, frm, to, page.count, unsplittable, report, resume,
                progress)


def _fetch_leaf(client, conn, stage, config, frm, to, reported, unsplittable, report, resume,
                progress=None) -> None:
    slice_key = (stage, _fmt(frm), _fmt(to))
    if resume and _slice_done(conn, slice_key):
        return

    seen: set[str] = set()
    offset = 0
    while offset < reported:
        page = client.list_alphas(
            stage=stage, limit=config.page_size, offset=offset,
            date_created_gt=_fmt(frm), date_created_lt=_fmt(to),
        )
        if not page.items:
            break                      # offset 上限或平台提前收敛
        with _transaction(conn):
            for item in page.items:
                _upsert(conn, item, stage)
                seen.add(item["id"])
        offset += config.page_size

    status = "partial" if (unsplittable or len(seen) != reported) else "done"
    conn.execute(
        "INSERT INTO sync_slice(stage, slice_from, slice_to, reported_count, fetched_count,"
        " status, completed_at) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(stage, slice_from, slice_to) DO UPDATE SET"
        " reported_count=excluded.reported_count, fetched_count=excluded.fetched_count,"
        " status=excluded.status, completed_at=excluded.completed_at",
        (*slice_key, reported, len(seen), status, _now()),
    )
    report.fetched += len(seen)
    if progress:                       # 设计 §5：长任务必须能看出进度，否则会被误判卡死
        progress(f"[{stage}] 窗口 {_fmt(frm)} ~ {_fmt(to)}：拉取 {len(seen)}/{reported}，"
                 f"累计 {report.fetched} 条")
    if len(seen) != reported:          # 窗口级对账（主口径）
        report.mismatched_slices.append({"slice": slice_key, "reported": reported, "fetched": len(seen)})


# --- 增量 -----------------------------------------------------------------


def incremental_sync(client, conn: sqlite3.Connection, *, stage: str, config: Config) -> SyncReport:
    """增量语义严格等于「新增」（PRD #2 定稿口径）。

    已入库 Alpha 的平台字段刷新由全量重拉承担——不属增量职责。恢复路径要读平台
    真实状态时走 `client.get_alpha` 直查（设计 §4.6），不要指望这里。
    """
    report = SyncReport(stage=stage)
    watermark = db.get_meta(conn, f"last_sync_date_created:{stage}") or _local_max_date(conn, stage)

    offset = 0
    while True:
        page = client.list_alphas(
            stage=stage, limit=config.page_size, offset=offset,
            date_created_gt=watermark, order="dateCreated",
        )
        if not page.items:
            break
        with _transaction(conn):
            for item in page.items:
                _upsert(conn, item, stage)
                report.fetched += 1
        offset += config.page_size

    _update_watermark(conn, stage)
    report.local_count = _local_count(conn, stage)
    return report


# --- 内部 -----------------------------------------------------------------


def _upsert(conn, item: dict, stage: str) -> None:
    """平台原始字段 UPSERT；派生状态只在行不存在时创建（§4.2 ON CONFLICT DO NOTHING）。"""
    alpha_id = item["id"]
    conn.execute(
        "INSERT INTO alpha(alpha_id, stage, date_created, date_submitted, expression, raw_json, fetched_at)"
        " VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(alpha_id) DO UPDATE SET stage=excluded.stage,"
        " date_created=excluded.date_created, date_submitted=excluded.date_submitted,"
        " expression=excluded.expression, raw_json=excluded.raw_json, fetched_at=excluded.fetched_at",
        (
            alpha_id,
            item.get("stage", stage),
            item["dateCreated"],
            item.get("dateSubmitted"),
            (item.get("regular") or {}).get("code", ""),
            json.dumps(item, ensure_ascii=False),
            _now(),
        ),
    )
    db.ensure_state(conn, alpha_id, _INITIAL_STATUS.get(item.get("stage", stage), db.BACKTESTED))


def _offset_exhaust_count(client, stage, config: Config) -> int:
    """不带时间窗的 offset 直连穷尽，仅用于诊断 offset 是否封顶。"""
    seen: set[str] = set()
    offset = 0
    while True:
        page = client.list_alphas(stage=stage, limit=config.page_size, offset=offset)
        if not page.items:
            return len(seen)
        seen.update(item["id"] for item in page.items)
        offset += config.page_size


def _slice_done(conn, slice_key) -> bool:
    row = conn.execute(
        "SELECT status FROM sync_slice WHERE stage=? AND slice_from=? AND slice_to=?", slice_key
    ).fetchone()
    return row is not None and row["status"] == "done"


def _local_count(conn, stage) -> int:
    return conn.execute("SELECT COUNT(*) FROM alpha WHERE stage=?", (stage,)).fetchone()[0]


def _local_max_date(conn, stage) -> str | None:
    return conn.execute("SELECT MAX(date_created) FROM alpha WHERE stage=?", (stage,)).fetchone()[0]


def _update_watermark(conn, stage) -> None:
    newest = _local_max_date(conn, stage)
    if newest:
        db.set_meta(conn, f"last_sync_date_created:{stage}", newest)


@contextmanager
def _transaction(conn):
    conn.execute("BEGIN")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _fmt(moment: datetime) -> str:
    return moment.isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

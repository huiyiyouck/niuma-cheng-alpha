import json
from datetime import datetime

import pytest

from alpha_platform import db
from alpha_platform.client import AlphaListPage, CorrelationResult, SubmitOutcome


class FakePlatform:
    """客户端方法层替身（设计 §3.1.0 指定的默认替身层次）。

    按真实语义模拟：`dateCreated>` / `dateCreated<` 两端开区间、count 报告总数、
    offset 分页。`offset_ceiling` 可模拟平台的 offset 上限。
    """

    def __init__(self, alphas=None, *, offset_ceiling=None, correlations=None, submit_results=None,
                 details=None, total_override=None):
        self.alphas = list(alphas or [])
        self.total_override = total_override   # 不带时间窗查询时平台报告的总数（A17 用）
        self.offset_ceiling = offset_ceiling
        self.correlations = correlations or {}
        self.submit_results = submit_results or {}
        self.details = details or {}
        self.calls = []

    def list_alphas(self, *, stage, limit, offset, date_created_gt=None, date_created_lt=None,
                    order="dateCreated"):
        self.calls.append(("list_alphas", stage, date_created_gt, date_created_lt, offset))
        items = [a for a in self.alphas if a["stage"] == stage]
        if date_created_gt is not None:
            items = [a for a in items if _dt(a["dateCreated"]) > _dt(date_created_gt)]
        if date_created_lt is not None:
            items = [a for a in items if _dt(a["dateCreated"]) < _dt(date_created_lt)]
        items.sort(key=lambda a: _dt(a["dateCreated"]), reverse=order.startswith("-"))
        window = items[offset : offset + limit]
        if self.offset_ceiling is not None:
            window = [a for i, a in enumerate(window, start=offset) if i < self.offset_ceiling]
        no_window = date_created_gt is None and date_created_lt is None
        count = self.total_override if (no_window and self.total_override is not None) else len(items)
        return AlphaListPage(count=count, items=window)

    def get_alpha(self, alpha_id):
        self.calls.append(("get_alpha", alpha_id))
        return self.details[alpha_id]

    def get_self_correlation(self, alpha_id):
        self.calls.append(("get_self_correlation", alpha_id))
        return _as_correlation(self.correlations.get((alpha_id, "self")))

    def get_prod_correlation(self, alpha_id):
        self.calls.append(("get_prod_correlation", alpha_id))
        return _as_correlation(self.correlations.get((alpha_id, "prod")))

    def submit_alpha(self, alpha_id):
        self.calls.append(("submit_alpha", alpha_id))
        outcome = self.submit_results.get(alpha_id, True)
        if outcome is True:
            return SubmitOutcome(ok=True, error=None, raw={"id": alpha_id})
        return SubmitOutcome(ok=False, error=str(outcome), raw=None)


def _as_correlation(value):
    return CorrelationResult(max_correlation=value, attempts=1, raw={"schema": {"max": value}})


def _dt(text):
    return datetime.fromisoformat(text)


def platform_alpha(alpha_id, date_created, *, stage="IS", checks=None, expression="rank(close)"):
    return {
        "id": alpha_id,
        "stage": stage,
        "dateCreated": date_created,
        "regular": {"code": expression},
        "is": {"checks": checks or []},
    }


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "inventory.db")
    yield connection
    connection.close()


def make_check(name, result, value=None, limit=None):
    check = {"name": name, "result": result}
    if value is not None:
        check["value"] = value
    if limit is not None:
        check["limit"] = limit
    return check


def insert_alpha(conn, alpha_id, *, stage="IS", checks=None, date_created="2026-01-24T09:00:00-04:00",
                 expression="rank(close)", funnel_status=None, **state):
    """插入一条平台记录 + 可选的派生状态。"""
    raw = {
        "id": alpha_id,
        "stage": stage,
        "dateCreated": date_created,
        "regular": {"code": expression},
        "is": {"checks": checks or []},
    }
    conn.execute(
        "INSERT INTO alpha(alpha_id, stage, date_created, expression, raw_json, fetched_at)"
        " VALUES (?,?,?,?,?,'2026-08-15T00:00:00Z')",
        (alpha_id, stage, date_created, expression, json.dumps(raw)),
    )
    if funnel_status is not None:
        db.ensure_state(conn, alpha_id, funnel_status)
        if state:
            sets = ", ".join(f"{k} = ?" for k in state)
            conn.execute(
                f"UPDATE alpha_state SET {sets} WHERE alpha_id = ?",
                (*state.values(), alpha_id),
            )
    return alpha_id


def state_of(conn, alpha_id):
    return conn.execute("SELECT * FROM alpha_state WHERE alpha_id = ?", (alpha_id,)).fetchone()

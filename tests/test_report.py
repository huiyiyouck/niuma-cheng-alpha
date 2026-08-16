"""漏斗报告测试：PRD #7 / #3，设计 §4.5。"""
import json

from alpha_platform import db, report

from .conftest import insert_alpha, make_check


def _classified(conn, alpha_id, status, *, gate_fails=(), non_gate=(), **state):
    insert_alpha(conn, alpha_id, funnel_status=status, **state)
    conn.execute(
        "UPDATE alpha_state SET classify_reason_json=? WHERE alpha_id=?",
        (json.dumps({"verdict": status, "gate_fails": list(gate_fails), "non_gate": list(non_gate)}), alpha_id),
    )


def test_各状态数量按七态统计且不含未回测级(conn):
    _classified(conn, "A1", db.SUBMITTABLE)
    _classified(conn, "A2", db.REWORK, status_source="classify")
    _classified(conn, "S1", db.SUBMITTED)

    data = report.build(conn)

    assert data["status_counts"][db.SUBMITTABLE] == 1
    assert data["status_counts"][db.SUBMITTED] == 1
    assert "未回测" not in data["status_counts"]


def test_改造候选按来源拆两行(conn):
    """Q5：因 checks FAIL 与因相关性超阈，后续处置完全不同。"""
    _classified(conn, "A1", db.REWORK, status_source="classify")
    _classified(conn, "A2", db.REWORK, status_source="prediction", prediction_result="fail")

    data = report.build(conn)

    assert data["rework_by_source"] == {"classify": 1, "prediction": 1}


def test_FAIL_卡点分布按_check_聚合次数与平均_gap(conn):
    _classified(conn, "A1", db.REWORK, gate_fails=[
        {"name": "LOW_SHARPE", "gap": 0.2, "quantifiable": True},
        {"name": "LOW_FITNESS", "gap": 0.1, "quantifiable": True},
    ])
    _classified(conn, "A2", db.REWORK, gate_fails=[{"name": "LOW_SHARPE", "gap": 0.4, "quantifiable": True}])

    top = {row["name"]: row for row in report.build(conn)["fail_top"]}

    assert top["LOW_SHARPE"]["count"] == 2
    assert round(top["LOW_SHARPE"]["avg_gap"], 3) == 0.3
    assert top["LOW_FITNESS"]["count"] == 1


def test_携带未判定门槛类_check_的候选数对_Owner_可见(conn):
    """A12：CLUSTER_TEST 全样本 ERROR，若日后证实是硬门槛，当前分流整体偏乐观。"""
    _classified(conn, "A1", db.SUBMITTABLE, non_gate=[{"name": "CLUSTER_TEST", "result": "ERROR"}])
    _classified(conn, "A2", db.SUBMITTABLE, non_gate=[{"name": "UNITS", "result": "WARNING"}])
    _classified(conn, "A3", db.SUBMITTABLE)

    assert report.build(conn)["undetermined_gate_candidates"] == 1


def test_待定条数只计仍是可提交候选的记录(conn):
    """Q7：阈值调紧后被重算为淘汰候选的记录，不该还提示 Owner 去 --retry-pending。"""
    _classified(conn, "A1", db.SUBMITTABLE, is_pending_flag=1, prediction_result="pending")
    _classified(conn, "A2", db.DISCARD, is_pending_flag=1, prediction_result="pending")

    assert report.build(conn)["pending_count"] == 1


def test_按状态查询输出记录清单(conn):
    """PRD #3 在 CLI 层的落点，也是 --reset 取 ID 的来源（D15）。"""
    _classified(conn, "A1", db.REWORK, gate_fails=[{"name": "LOW_SHARPE", "gap": 0.2}])
    _classified(conn, "A2", db.SUBMITTABLE)

    rows = report.list_by_status(conn, db.REWORK)

    assert [r["alpha_id"] for r in rows] == ["A1"]
    assert rows[0]["expression"] == "rank(close)"


def test_文本与_json_两种输出格式(conn):
    _classified(conn, "A1", db.SUBMITTABLE)

    text = report.render(report.build(conn), fmt="text")
    payload = json.loads(report.render(report.build(conn), fmt="json"))

    assert db.SUBMITTABLE in text
    assert payload["status_counts"][db.SUBMITTABLE] == 1

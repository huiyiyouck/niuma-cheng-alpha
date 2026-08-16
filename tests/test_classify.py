"""分流测试：PRD #4 / #5，设计 §3.2 规则与 §4.3 适用域·写回逻辑。"""
import json

import pytest

from alpha_platform import classify, db

from .conftest import insert_alpha, make_check, state_of


# --- 纯函数规则（PRD #5 的单测入口，无 IO） --------------------------------


def test_无_FAIL_归可提交候选():
    result = classify.classify_checks([make_check("LOW_SHARPE", "PASS", 2.1, 1.58)], 0.3)
    assert result.funnel_status == db.SUBMITTABLE
    assert result.reason["gate_fails"] == []
    assert result.reason["gate_passes"] == ["LOW_SHARPE"]


def test_FAIL_差距在阈值内归改造候选并记录_gap():
    # value=1.21 limit=1.58 → gap = 0.37/1.58 ≈ 0.234 ≤ 0.3
    result = classify.classify_checks([make_check("LOW_SHARPE", "FAIL", 1.21, 1.58)], 0.3)
    assert result.funnel_status == db.REWORK
    fail = result.reason["gate_fails"][0]
    assert fail["name"] == "LOW_SHARPE"
    assert round(fail["gap"], 3) == 0.234
    assert fail["quantifiable"] is True


def test_任一_FAIL_差距超阈值归淘汰候选():
    checks = [
        make_check("LOW_SHARPE", "FAIL", 1.5, 1.58),   # gap ≈ 0.05
        make_check("LOW_FITNESS", "FAIL", 0.2, 1.0),   # gap = 0.8 > 0.3
    ]
    assert classify.classify_checks(checks, 0.3).funnel_status == db.DISCARD


def test_非门槛项不参与判定但必须留痕():
    """WARNING / ERROR / PENDING 一律非门槛（CLUSTER_TEST 全 ERROR、UNITS 常 WARNING）。"""
    checks = [
        make_check("CLUSTER_TEST", "ERROR"),
        make_check("UNITS", "WARNING"),
        make_check("SELF_CORRELATION", "PENDING"),
        make_check("LOW_SHARPE", "PASS", 2.0, 1.58),
    ]
    result = classify.classify_checks(checks, 0.3)
    assert result.funnel_status == db.SUBMITTABLE
    assert {n["name"] for n in result.reason["non_gate"]} == {
        "CLUSTER_TEST",
        "UNITS",
        "SELF_CORRELATION",
    }


def test_不可量化的_FAIL_保守归改造候选():
    """value/limit 缺省或 limit==0 → 标 quantifiable false，按「差距在阈值内」处理。"""
    for check in (
        make_check("CONCENTRATED_WEIGHT", "FAIL"),
        make_check("IS_LADDER_SHARPE", "FAIL", 0.4, 0),
    ):
        result = classify.classify_checks([check], 0.3)
        assert result.funnel_status == db.REWORK
        assert result.reason["gate_fails"][0]["quantifiable"] is False


def test_达标线随平台返回值变化而非硬编码():
    """PRD #5：注入不同 limit，分流结果随之变化。"""
    low = classify.classify_checks([make_check("LOW_SHARPE", "FAIL", 1.5, 1.58)], 0.3)
    high = classify.classify_checks([make_check("LOW_SHARPE", "FAIL", 1.5, 3.0)], 0.3)
    assert low.funnel_status == db.REWORK      # gap ≈ 0.05
    assert high.funnel_status == db.DISCARD    # gap = 0.5


def test_理由带规则版本与阈值():
    result = classify.classify_checks([make_check("LOW_SHARPE", "PASS", 2.0, 1.58)], 0.42)
    assert result.reason["rule_version"] == classify.RULE_VERSION
    assert result.reason["threshold"] == 0.42


# --- 库层：适用域与写回（设计 §4.3） --------------------------------------


def test_全量覆盖无未分类残留且守恒断言成立(conn):
    insert_alpha(conn, "A1", checks=[make_check("LOW_SHARPE", "PASS", 2.0, 1.58)], funnel_status=db.BACKTESTED)
    insert_alpha(conn, "A2", checks=[make_check("LOW_SHARPE", "FAIL", 1.2, 1.58)], funnel_status=db.BACKTESTED)
    insert_alpha(conn, "A3", checks=[make_check("LOW_FITNESS", "FAIL", 0.1, 1.0)], funnel_status=db.BACKTESTED)

    classify.run(conn, threshold=0.3)

    statuses = {r["alpha_id"]: r["funnel_status"] for r in conn.execute("SELECT * FROM alpha_state")}
    assert statuses == {"A1": db.SUBMITTABLE, "A2": db.REWORK, "A3": db.DISCARD}
    assert conn.execute("SELECT COUNT(*) FROM alpha_state WHERE classify_reason_json IS NULL").fetchone()[0] == 0
    # 守恒（D20）：alpha 行数 == alpha_state 行数 == 已回测 + 三类候选 + 保护态
    assert classify.conservation_holds(conn)


def test_保护态永不参与重算(conn):
    for status in db.PROTECTED_STATUSES:
        insert_alpha(conn, f"P-{status}", checks=[make_check("LOW_FITNESS", "FAIL", 0.1, 1.0)],
                     funnel_status=status)

    classify.run(conn, threshold=0.3)

    for status in db.PROTECTED_STATUSES:
        assert state_of(conn, f"P-{status}")["funnel_status"] == status


def test_从未预判的改造候选在改阈值后归属随之变化(conn):
    """§8 第 6 条第 5 项指定用例——D16 的针对性覆盖。

    这条记录 `prediction_result IS NULL`；R2 版把 fail 判断写进 WHERE 时，
    它会被 `NULL = 'fail'` 求值为 NULL 而静默排除，改阈值后归属不变而验收仍全绿。
    """
    insert_alpha(conn, "A1", checks=[make_check("LOW_SHARPE", "FAIL", 1.1, 1.58)],  # gap ≈ 0.304
                 funnel_status=db.REWORK, status_source="classify")
    assert state_of(conn, "A1")["prediction_result"] is None

    classify.run(conn, threshold=0.5)
    assert state_of(conn, "A1")["funnel_status"] == db.REWORK

    classify.run(conn, threshold=0.2)
    assert state_of(conn, "A1")["funnel_status"] == db.DISCARD


def test_预判判死的记录锁定状态但理由照常刷新(conn):
    """D14 + D17：状态与来源要真，理由要新。"""
    insert_alpha(conn, "A1", checks=[make_check("LOW_SHARPE", "PASS", 2.0, 1.58)],
                 funnel_status=db.REWORK, status_source="prediction", prediction_result="fail")

    classify.run(conn, threshold=0.3)

    row = state_of(conn, "A1")
    assert row["funnel_status"] == db.REWORK          # 按 checks 本应回到「可提交候选」
    assert row["status_source"] == "prediction"
    assert json.loads(row["classify_reason_json"])["verdict"] == db.SUBMITTABLE  # 理由已刷新
    assert row["classify_threshold"] == 0.3


def test_重算不触碰预判侧字段(conn):
    """A9 + Q7：prediction_* 与 is_pending_flag 同属预判侧。"""
    insert_alpha(conn, "A1", checks=[make_check("LOW_SHARPE", "PASS", 2.0, 1.58)],
                 funnel_status=db.SUBMITTABLE, prediction_result="pending", is_pending_flag=1)

    classify.run(conn, threshold=0.3)

    row = state_of(conn, "A1")
    assert row["prediction_result"] == "pending"
    assert row["is_pending_flag"] == 1


def test_scope_unclassified_只处理未分流记录(conn):
    insert_alpha(conn, "A1", checks=[make_check("LOW_SHARPE", "PASS", 2.0, 1.58)], funnel_status=db.BACKTESTED)
    insert_alpha(conn, "A2", checks=[make_check("LOW_SHARPE", "PASS", 2.0, 1.58)],
                 funnel_status=db.DISCARD, classified_at="2026-08-15T00:00:00Z")

    classify.run(conn, threshold=0.3, scope="unclassified")

    assert state_of(conn, "A1")["funnel_status"] == db.SUBMITTABLE
    assert state_of(conn, "A2")["funnel_status"] == db.DISCARD  # 未被重算


def test_重算中途失败不留下混合态(conn):
    """A20：中途失败若留下「部分新阈值、部分旧阈值」，report 会给出误导性的混合结果。"""
    insert_alpha(conn, "A1", checks=[make_check("LOW_SHARPE", "PASS", 2.0, 1.58)], funnel_status=db.BACKTESTED)
    insert_alpha(conn, "A2", checks=[make_check("LOW_SHARPE", "PASS", 2.0, 1.58)], funnel_status=db.BACKTESTED)
    classify.run(conn, threshold=0.3)

    original = classify.classify_checks

    def exploding(checks, threshold):
        if threshold == 0.9:
            raise RuntimeError("算到一半崩了")
        return original(checks, threshold)

    classify.classify_checks = exploding
    try:
        with pytest.raises(RuntimeError):
            classify.run(conn, threshold=0.9)
    finally:
        classify.classify_checks = original

    thresholds = {r[0] for r in conn.execute("SELECT classify_threshold FROM alpha_state")}
    assert thresholds == {0.3}          # 全部停在旧阈值，没有混合态

"""提交前预判测试：PRD #6，设计 §4.4 两阶段短路、候选集守卫、三态出口。"""
import json

import pytest

from alpha_platform import db, precheck
from alpha_platform.config import Config

from .conftest import FakePlatform, insert_alpha, state_of

CFG = Config(correlation_threshold=0.7)


def test_两路均低于阈值判通过并转待确认(conn):
    insert_alpha(conn, "A1", funnel_status=db.SUBMITTABLE)
    platform = FakePlatform(correlations={("A1", "self"): 0.4, ("A1", "prod"): 0.5})

    precheck.run(platform, conn, config=CFG)

    row = state_of(conn, "A1")
    assert row["prediction_result"] == "pass"
    assert row["funnel_status"] == db.PENDING_CONFIRM
    assert row["status_source"] == "prediction"


def test_self_超阈直接判死且不调用_prod_接口(conn):
    """短路：self-corr 超阈时 prod-corr 必然超阈，最坏调用次数减半。"""
    insert_alpha(conn, "A1", funnel_status=db.SUBMITTABLE)
    platform = FakePlatform(correlations={("A1", "self"): 0.83, ("A1", "prod"): 0.9})

    precheck.run(platform, conn, config=CFG)

    assert state_of(conn, "A1")["funnel_status"] == db.REWORK
    assert state_of(conn, "A1")["prediction_result"] == "fail"
    assert not any(c[0] == "get_prod_correlation" for c in platform.calls)


def test_重试耗尽标待定且不阻塞其余候选(conn):
    """PRD #6 第三态出口：待定不是独立状态，是「可提交候选」上的标注。"""
    insert_alpha(conn, "A1", funnel_status=db.SUBMITTABLE)
    insert_alpha(conn, "A2", funnel_status=db.SUBMITTABLE)
    platform = FakePlatform(correlations={
        ("A1", "self"): None,                       # 重试耗尽
        ("A2", "self"): 0.3, ("A2", "prod"): 0.3,
    })

    precheck.run(platform, conn, config=CFG)

    a1 = state_of(conn, "A1")
    assert a1["prediction_result"] == "pending"
    assert a1["funnel_status"] == db.SUBMITTABLE
    assert a1["is_pending_flag"] == 1
    assert state_of(conn, "A2")["prediction_result"] == "pass"   # 未被阻塞


def test_已有结论的记录被跳过_不重复消耗配额(conn):
    """A9：`prediction_result` 非空即「已有结论」，与断点续跑是同一件事。"""
    insert_alpha(conn, "A1", funnel_status=db.SUBMITTABLE, prediction_result="fail")
    platform = FakePlatform(correlations={("A1", "self"): 0.1})

    precheck.run(platform, conn, config=CFG)

    assert platform.calls == []


def test_retry_pending_把待定记录重新纳入候选集(conn):
    insert_alpha(conn, "A1", funnel_status=db.SUBMITTABLE, prediction_result="pending", is_pending_flag=1)
    platform = FakePlatform(correlations={("A1", "self"): 0.2, ("A1", "prod"): 0.2})

    precheck.run(platform, conn, config=CFG, retry_pending=True)

    row = state_of(conn, "A1")
    assert row["prediction_result"] == "pass"
    assert row["is_pending_flag"] == 0


def test_reset_可点名改造候选中因预判判死的记录(conn):
    insert_alpha(conn, "A1", funnel_status=db.REWORK, status_source="prediction", prediction_result="fail")
    platform = FakePlatform(correlations={("A1", "self"): 0.1, ("A1", "prod"): 0.1})

    precheck.run(platform, conn, config=CFG, reset=["A1"])

    assert state_of(conn, "A1")["funnel_status"] == db.PENDING_CONFIRM


def test_reset_点名保护态记录时明确报错而非静默跳过(conn):
    """D18：静默跳过会让 Owner 以为重置成功了。"""
    insert_alpha(conn, "S1", funnel_status=db.SUBMITTED)
    platform = FakePlatform()

    with pytest.raises(precheck.ResetGuardError):
        precheck.run(platform, conn, config=CFG, reset=["S1"])

    assert platform.calls == []


def test_reset_点名因_checks_归入的改造候选同样被拒(conn):
    """D23：它重新预判若通过会进提交清单——一条 checks 未达标的 Alpha 排队等提交。"""
    insert_alpha(conn, "A1", funnel_status=db.REWORK, status_source="classify")
    with pytest.raises(precheck.ResetGuardError):
        precheck.run(FakePlatform(), conn, config=CFG, reset=["A1"])


def test_保护态永不进入常规候选集(conn):
    for status in db.PROTECTED_STATUSES:
        insert_alpha(conn, f"P-{status}", funnel_status=status)
    platform = FakePlatform()

    precheck.run(platform, conn, config=CFG)

    assert platform.calls == []


def test_阈值与来源写入每条预判结论(conn):
    """PRD #6：阈值必带来源字段，不允许无来源硬编码。"""
    insert_alpha(conn, "A1", funnel_status=db.SUBMITTABLE)
    platform = FakePlatform(correlations={("A1", "self"): 0.9})

    precheck.run(platform, conn, config=CFG)

    reason = json.loads(state_of(conn, "A1")["prediction_reason_json"])
    assert reason["threshold"] == {"value": 0.7, "source": "convention_demo"}
    assert reason["self_correlation"] == 0.9
    assert reason["short_circuited"] is True


def test_limit_限制本次处理条数(conn):
    for i in range(5):
        insert_alpha(conn, f"A{i}", funnel_status=db.SUBMITTABLE)
    platform = FakePlatform(correlations={(f"A{i}", "self"): 0.9 for i in range(5)})

    precheck.run(platform, conn, config=CFG, limit=2)

    done = conn.execute("SELECT COUNT(*) FROM alpha_state WHERE prediction_result IS NOT NULL").fetchone()[0]
    assert done == 2


def test_每条结论立即落库_中断不丢已完成部分(conn):
    """断点续跑：任意时刻中断，已完成部分不丢，重跑自动跳过。"""
    insert_alpha(conn, "A1", funnel_status=db.SUBMITTABLE)
    insert_alpha(conn, "A2", funnel_status=db.SUBMITTABLE)

    class Exploding(FakePlatform):
        def get_self_correlation(self, alpha_id):
            if alpha_id == "A2":
                raise RuntimeError("网络断了")
            return super().get_self_correlation(alpha_id)

    platform = Exploding(correlations={("A1", "self"): 0.9})
    with pytest.raises(RuntimeError):
        precheck.run(platform, conn, config=CFG)

    assert state_of(conn, "A1")["prediction_result"] == "fail"    # 已落库
    assert state_of(conn, "A2")["prediction_result"] is None

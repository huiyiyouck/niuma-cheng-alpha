"""同步测试：PRD #1 / #2 / #3 / #10，设计 §4.1 切片与对账、§4.2 增量与初始态。"""
from alpha_platform import db, sync
from alpha_platform.config import Config

from .conftest import FakePlatform, platform_alpha, state_of

TZ = "-04:00"


def at(day, hour=9, minute=0, second=0):
    return f"2026-01-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}{TZ}"


def test_全量同步落库并按_stage_建初始态(conn):
    platform = FakePlatform([
        platform_alpha("A1", at(24)),
        platform_alpha("A2", at(25)),
        platform_alpha("S1", at(20), stage="OS"),
    ])
    cfg = Config(split_threshold=9000, page_size=100)

    sync.full_sync(platform, conn, stage="IS", config=cfg)
    sync.full_sync(platform, conn, stage="OS", config=cfg)

    assert {r[0] for r in conn.execute("SELECT alpha_id FROM alpha")} == {"A1", "A2", "S1"}
    # PRD §3.1：IS → 已回测，OS → 已提交（88 条已提交必须进得了报告）
    assert state_of(conn, "A1")["funnel_status"] == db.BACKTESTED
    assert state_of(conn, "S1")["funnel_status"] == db.SUBMITTED
    assert conn.execute("SELECT expression FROM alpha WHERE alpha_id='A1'").fetchone()[0] == "rank(close)"


def test_时间轴首末两端的记录不丢(conn):
    """§8 第 6 条第 1 项（D9）——根窗口两端开区间会静默丢掉 T_min / T_max 同秒的记录，
    而窗口级对账左右值同源、查不出来。这里三条 alpha 恰好压在边界与同一秒上。"""
    platform = FakePlatform([
        platform_alpha("FIRST-a", at(24, 9, 0, 0)),
        platform_alpha("FIRST-b", at(24, 9, 0, 0)),   # 与最早条同一秒
        platform_alpha("MID", at(26)),
        platform_alpha("LAST", at(28, 17, 30, 15)),
    ])

    report = sync.full_sync(platform, conn, stage="IS", config=Config())

    assert {r[0] for r in conn.execute("SELECT alpha_id FROM alpha")} == {
        "FIRST-a", "FIRST-b", "MID", "LAST",
    }
    assert report.local_count == 4


def test_窗口级对账为主口径且逐窗口相等(conn):
    platform = FakePlatform([platform_alpha(f"A{i}", at(24, 9, 0, i)) for i in range(10)])
    cfg = Config(split_threshold=3, page_size=2)   # 强制多层递归切片 + 多页穷尽

    report = sync.full_sync(platform, conn, stage="IS", config=cfg)

    assert report.reconciled is True
    slices = conn.execute("SELECT reported_count, fetched_count, status FROM sync_slice").fetchall()
    assert len(slices) > 1                                  # 确实发生了细分
    assert all(s["reported_count"] == s["fetched_count"] for s in slices)
    assert report.local_count == 10


def test_递归在窄窗口收敛而非无限下探(conn):
    """§8 第 6 条第 3 项（D11）：同一秒内挤满记录时，切分必须停在 partial 而不是栈溢出。"""
    platform = FakePlatform([platform_alpha(f"A{i}", at(24, 9, 0, 0)) for i in range(12)])
    cfg = Config(split_threshold=3, page_size=100)

    report = sync.full_sync(platform, conn, stage="IS", config=cfg)

    assert report.local_count == 12
    assert any(s["status"] == "partial" for s in conn.execute("SELECT status FROM sync_slice"))


def test_断点续跑跳过已完成窗口(conn):
    """PRD #10：中断后重跑只重做未完成窗口。"""
    platform = FakePlatform([platform_alpha(f"A{i}", at(24, 9, 0, i)) for i in range(6)])
    cfg = Config(split_threshold=2, page_size=10)
    sync.full_sync(platform, conn, stage="IS", config=cfg)
    first_round = len([c for c in platform.calls if c[0] == "list_alphas"])

    platform.calls.clear()
    sync.full_sync(platform, conn, stage="IS", config=cfg, resume=True)
    second_round = len([c for c in platform.calls if c[0] == "list_alphas"])

    assert second_round < first_round
    assert conn.execute("SELECT COUNT(*) FROM alpha").fetchone()[0] == 6


def test_连续两次全量同步幂等(conn):
    platform = FakePlatform([platform_alpha(f"A{i}", at(24, 9, 0, i)) for i in range(5)])
    cfg = Config(split_threshold=2, page_size=10)

    sync.full_sync(platform, conn, stage="IS", config=cfg, resume=False)
    first = conn.execute("SELECT COUNT(*) FROM alpha").fetchone()[0]
    sync.full_sync(platform, conn, stage="IS", config=cfg, resume=False)
    second = conn.execute("SELECT COUNT(*) FROM alpha").fetchone()[0]

    assert first == second == 5


def test_offset_封顶被检出并留痕(conn):
    # 切片后每个窗口都小于上限、能拉全；只有不带时间窗的 offset 直连会撞上限。
    platform = FakePlatform(
        [platform_alpha(f"A{i}", at(24, 9, 0, i)) for i in range(8)], offset_ceiling=5
    )
    cfg = Config(split_threshold=3, page_size=2)

    sync.full_sync(platform, conn, stage="IS", config=cfg)

    ceiling = db.get_meta(conn, "offset_ceiling_detected")
    assert ceiling is not None and '"detected": true' in ceiling


def test_增量同步只拉新增且幂等(conn):
    platform = FakePlatform([platform_alpha("A1", at(24)), platform_alpha("A2", at(25))])
    cfg = Config()
    sync.full_sync(platform, conn, stage="IS", config=cfg)

    platform.alphas.append(platform_alpha("A3", at(26)))
    platform.calls.clear()
    report = sync.incremental_sync(platform, conn, stage="IS", config=cfg)

    assert report.fetched == 1
    assert sync.incremental_sync(platform, conn, stage="IS", config=cfg).fetched == 0
    assert conn.execute("SELECT COUNT(*) FROM alpha").fetchone()[0] == 3


def test_再次同步刷新平台字段但派生字段保持不变(conn):
    """PRD #3：分层存储——同步只刷新平台字段。"""
    platform = FakePlatform([platform_alpha("A1", at(24), expression="rank(close)")])
    cfg = Config()
    sync.full_sync(platform, conn, stage="IS", config=cfg)
    conn.execute(
        "UPDATE alpha_state SET funnel_status='待确认', prediction_result='pass',"
        " classify_reason_json='{\"verdict\":\"可提交候选\"}' WHERE alpha_id='A1'"
    )

    platform.alphas[0]["regular"]["code"] = "rank(volume)"
    sync.full_sync(platform, conn, stage="IS", config=cfg, resume=False)

    assert conn.execute("SELECT expression FROM alpha").fetchone()[0] == "rank(volume)"
    row = state_of(conn, "A1")
    assert row["funnel_status"] == "待确认"
    assert row["prediction_result"] == "pass"
    assert row["classify_reason_json"] == '{"verdict":"可提交候选"}'

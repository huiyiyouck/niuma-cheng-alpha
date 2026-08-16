"""提交测试：PRD #8，设计 §4.6——唯一不可逆动作的三重兜底与恢复路径。"""
import json

import pytest

from alpha_platform import db, submit

from .conftest import FakePlatform, insert_alpha, state_of


def _candidate(conn, alpha_id, **state):
    insert_alpha(conn, alpha_id, funnel_status=db.PENDING_CONFIRM,
                 prediction_result="pass", status_source="prediction", **state)


def _snapshots(tmp_path):
    return tmp_path / "snapshots"


# --- dry-run（零调用是硬闸） ----------------------------------------------


def test_dry_run_列清单与指纹且提交接口零调用(conn, tmp_path):
    _candidate(conn, "A2")
    _candidate(conn, "A1")
    platform = FakePlatform()

    result = submit.dry_run(conn)

    assert [i["alpha_id"] for i in result.items] == ["A1", "A2"]   # 按 alpha_id 升序
    assert len(result.fingerprint) == 64
    assert platform.calls == []


def test_清单内容变化则指纹变化_确认失效(conn):
    _candidate(conn, "A1")
    before = submit.dry_run(conn).fingerprint

    _candidate(conn, "A2")
    assert submit.dry_run(conn).fingerprint != before


def test_指纹不匹配时拒绝提交且零调用(conn, tmp_path):
    _candidate(conn, "A1")
    platform = FakePlatform()

    with pytest.raises(submit.FingerprintMismatch):
        submit.confirm(platform, conn, fingerprint="deadbeef", snapshot_dir=_snapshots(tmp_path))

    assert platform.calls == []
    assert state_of(conn, "A1")["funnel_status"] == db.PENDING_CONFIRM


# --- confirm ---------------------------------------------------------------


def test_确认后逐条提交并回写结果(conn, tmp_path):
    _candidate(conn, "A1")
    _candidate(conn, "A2")
    platform = FakePlatform(submit_results={"A2": "not eligible"})
    fingerprint = submit.dry_run(conn).fingerprint

    report = submit.confirm(platform, conn, fingerprint=fingerprint, snapshot_dir=_snapshots(tmp_path))

    a1, a2 = state_of(conn, "A1"), state_of(conn, "A2")
    assert a1["funnel_status"] == db.SUBMITTED and a1["submit_result"] == "success"
    assert a2["funnel_status"] == db.SUBMIT_FAILED and "not eligible" in a2["submit_error"]
    assert report.succeeded == 1 and report.failed == 1


def test_意向快照先落盘_提交前即存在证据(conn, tmp_path):
    """Q6：最需要证据的时刻恰是提交中途死亡时。"""
    _candidate(conn, "A1")
    snapshots = _snapshots(tmp_path)
    seen = {}

    class Watching(FakePlatform):
        def submit_alpha(self, alpha_id):
            seen["files"] = list(snapshots.glob("*.json"))
            seen["payload"] = json.loads(seen["files"][0].read_text(encoding="utf-8"))
            return super().submit_alpha(alpha_id)

    platform = Watching()
    submit.confirm(platform, conn, fingerprint=submit.dry_run(conn).fingerprint, snapshot_dir=snapshots)

    assert len(seen["files"]) == 1                      # POST 之前快照已在盘上
    assert seen["payload"]["items"][0]["result"] is None  # 结果字段留空，事后补齐


def test_快照写盘失败则终止_不进入提交循环(conn, tmp_path):
    """N12：证据写不下就不执行不可逆动作。"""
    _candidate(conn, "A1")
    blocked = tmp_path / "blocked"
    blocked.write_text("不是目录", encoding="utf-8")     # 让快照目录无法创建
    platform = FakePlatform()

    with pytest.raises(OSError):
        submit.confirm(platform, conn, fingerprint=submit.dry_run(conn).fingerprint, snapshot_dir=blocked)

    assert platform.calls == []


def test_快照事后补齐逐条结果(conn, tmp_path):
    _candidate(conn, "A1")
    snapshots = _snapshots(tmp_path)

    submit.confirm(FakePlatform(), conn, fingerprint=submit.dry_run(conn).fingerprint, snapshot_dir=snapshots)

    payload = json.loads(list(snapshots.glob("*.json"))[0].read_text(encoding="utf-8"))
    assert payload["items"][0]["result"] == "success"
    assert payload["fingerprint"] and payload["confirmed_at"]


def test_提交前先写_in_flight_意向标记(conn, tmp_path):
    """N8：POST 成功但写库前进程死亡时，本地要留下「这条正在飞」的痕迹。"""
    _candidate(conn, "A1")

    class Dying(FakePlatform):
        def submit_alpha(self, alpha_id):
            raise RuntimeError("进程被杀")

    with pytest.raises(RuntimeError):
        submit.confirm(Dying(), conn, fingerprint=submit.dry_run(conn).fingerprint,
                       snapshot_dir=_snapshots(tmp_path))

    assert state_of(conn, "A1")["submit_result"] == "in_flight"


def test_存在_in_flight_时拒绝进入提交流程(conn, tmp_path):
    """D19/N11：不确定的状态下不碰不可逆动作。"""
    _candidate(conn, "A1", submit_result="in_flight")
    _candidate(conn, "A2")
    platform = FakePlatform()

    with pytest.raises(submit.InFlightPending):
        submit.confirm(platform, conn, fingerprint=submit.dry_run(conn).fingerprint,
                       snapshot_dir=_snapshots(tmp_path))

    assert platform.calls == []


# --- reconcile（恢复路径） -------------------------------------------------


def test_reconcile_按平台真实状态收敛为已提交(conn, tmp_path):
    """§8 第 6 条第 6 项（D21/N14）指定用例：常规链路（list_alphas）拿不到该 alpha
    的新状态，直查（get_alpha）能拿到——收敛必须以直查为准，否则会再次 POST。"""
    _candidate(conn, "A1", submit_result="in_flight")
    platform = FakePlatform(
        alphas=[],                                   # 增量/列表查询里根本看不到它
        details={"A1": {"id": "A1", "stage": "OS", "dateSubmitted": "2026-08-15T10:00:00-04:00",
                        "regular": {"code": "rank(close)"}, "dateCreated": "2026-01-24T09:00:00-04:00"}},
    )

    report = submit.reconcile(platform, conn, snapshot_dir=_snapshots(tmp_path))

    row = state_of(conn, "A1")
    assert row["funnel_status"] == db.SUBMITTED
    assert row["submit_result"] == "success"
    assert row["submitted_at"] == "2026-08-15T10:00:00-04:00"
    assert report.unresolved == 0
    # D24：详情已在手，顺带把 alpha 表刷成平台真实值
    assert conn.execute("SELECT stage FROM alpha WHERE alpha_id='A1'").fetchone()[0] == "OS"


def test_reconcile_平台仍为_IS_则退回待确认(conn, tmp_path):
    _candidate(conn, "A1", submit_result="in_flight")
    platform = FakePlatform(details={"A1": {"id": "A1", "stage": "IS",
                                            "dateCreated": "2026-01-24T09:00:00-04:00",
                                            "regular": {"code": "rank(close)"}}})

    submit.reconcile(platform, conn, snapshot_dir=_snapshots(tmp_path))

    row = state_of(conn, "A1")
    assert row["funnel_status"] == db.PENDING_CONFIRM
    assert row["submit_result"] is None


def test_reconcile_查询失败时保持不动(conn, tmp_path):
    """N15：恢复路径的默认行为是「不确定就不动」。"""
    _candidate(conn, "A1", submit_result="in_flight")

    class Failing(FakePlatform):
        def get_alpha(self, alpha_id):
            raise RuntimeError("502")

    report = submit.reconcile(Failing(), conn, snapshot_dir=_snapshots(tmp_path))

    assert state_of(conn, "A1")["submit_result"] == "in_flight"
    assert report.unresolved == 1

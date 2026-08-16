"""CLI 测试：退出码映射与组装点（设计 §3.2、§3.1.0）。"""
import pytest

from alpha_platform import cli, db, submit

from .conftest import FakePlatform, insert_alpha, platform_alpha


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(argv, platform=None):
    return cli.main(argv, client_factory=(lambda: platform) if platform else None)


def test_sync_全量走通并建初始态(workspace):
    platform = FakePlatform([platform_alpha("A1", "2026-01-24T09:00:00-04:00")])
    assert run(["sync", "--full", "--stage", "IS"], platform) == cli.OK

    conn = db.connect(workspace / "data" / "inventory.db")
    assert conn.execute("SELECT COUNT(*) FROM alpha").fetchone()[0] == 1


def test_classify_与_report_串起来(workspace, capsys):
    platform = FakePlatform([
        platform_alpha("A1", "2026-01-24T09:00:00-04:00",
                       checks=[{"name": "LOW_SHARPE", "result": "PASS", "value": 2.0, "limit": 1.58}])
    ])
    run(["sync", "--full", "--stage", "IS"], platform)
    assert run(["classify"]) == cli.OK
    assert run(["report"]) == cli.OK

    assert db.SUBMITTABLE in capsys.readouterr().out


def test_dry_run_零调用并打印指纹(workspace, capsys):
    platform = FakePlatform([platform_alpha("A1", "2026-01-24T09:00:00-04:00")])
    run(["sync", "--full", "--stage", "IS"], platform)
    conn = db.connect(workspace / "data" / "inventory.db")
    conn.execute("UPDATE alpha_state SET funnel_status='待确认', prediction_result='pass'")
    conn.close()

    platform.calls.clear()
    assert run(["submit", "--dry-run"], platform) == cli.OK

    assert "指纹" in capsys.readouterr().out
    assert not any(c[0] == "submit_alpha" for c in platform.calls)


def test_指纹不匹配返回退出码_4(workspace):
    platform = FakePlatform([platform_alpha("A1", "2026-01-24T09:00:00-04:00")])
    run(["sync", "--full", "--stage", "IS"], platform)
    conn = db.connect(workspace / "data" / "inventory.db")
    conn.execute("UPDATE alpha_state SET funnel_status='待确认', prediction_result='pass'")
    conn.close()

    assert run(["submit", "--confirm", "deadbeef"], platform) == cli.FINGERPRINT_INVALID


def test_存在_in_flight_时返回退出码_6(workspace):
    platform = FakePlatform([platform_alpha("A1", "2026-01-24T09:00:00-04:00")])
    run(["sync", "--full", "--stage", "IS"], platform)
    conn = db.connect(workspace / "data" / "inventory.db")
    conn.execute("UPDATE alpha_state SET funnel_status='待确认', prediction_result='pass',"
                 " submit_result='in_flight'")
    conn.close()

    fingerprint = submit.dry_run(db.connect(workspace / "data" / "inventory.db")).fingerprint
    assert run(["submit", "--confirm", fingerprint], platform) == cli.IN_FLIGHT_PENDING


def test_reset_点名保护态返回退出码_3(workspace):
    platform = FakePlatform([platform_alpha("A1", "2026-01-24T09:00:00-04:00")])
    run(["sync", "--full", "--stage", "IS"], platform)
    conn = db.connect(workspace / "data" / "inventory.db")
    conn.execute("UPDATE alpha_state SET funnel_status='已提交'")
    conn.close()

    assert run(["precheck", "--reset", "A1"], platform) == cli.BAD_ARGS


def test_凭据缺失返回退出码_2(workspace):
    """PRD #9：明确报错并终止，不打印任何凭据内容。"""
    assert cli.main(["sync", "--incremental"]) == cli.AUTH_FAILED


def test_日志落在_data_logs_下(workspace):
    """N7：#9 的扫描断言需要确定的落盘位置。"""
    platform = FakePlatform([platform_alpha("A1", "2026-01-24T09:00:00-04:00")])
    run(["sync", "--full", "--stage", "IS"], platform)
    assert (workspace / "data" / "logs" / "alpha-platform.log").exists()


def test_日志与库文件不出现凭据字段名或认证串特征(workspace):
    """PRD #9 的结构化扫描断言：按字段名与 Basic 串特征扫描，不接触凭据明文。

    本测试自身不读取 `.brain_credentials`——扫描的是产物，不是凭据。
    """
    platform = FakePlatform([platform_alpha("A1", "2026-01-24T09:00:00-04:00")])
    run(["sync", "--full", "--stage", "IS"], platform)
    run(["classify"])

    artifacts = [
        workspace / "data" / "logs" / "alpha-platform.log",
        workspace / "data" / "inventory.db",
    ]
    for path in artifacts:
        blob = path.read_bytes().lower()
        assert b"password" not in blob
        assert b"credentials" not in blob
        assert b"authorization" not in blob
        assert b"basic " not in blob

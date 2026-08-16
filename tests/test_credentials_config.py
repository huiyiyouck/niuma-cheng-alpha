"""凭据加载与配置解析：PRD #9、设计 §4.7、L1（路径可环境变量覆盖）。"""
import json

import pytest

from alpha_platform import config as config_mod
from alpha_platform import credentials as creds_mod
from alpha_platform.client import AuthError

SECRET = "s3cret-value"


def _write_creds(path, email="someone@example.com", password=SECRET):
    path.write_text(json.dumps([email, password]), encoding="utf-8")
    return path


def test_从默认路径加载凭据(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_CREDENTIALS_PATH", raising=False)
    _write_creds(tmp_path / ".brain_credentials")
    creds = creds_mod.load(project_root=tmp_path)
    assert creds.email == "someone@example.com"
    assert creds.password == SECRET


def test_环境变量可覆盖路径(tmp_path, monkeypatch):
    """L1：为 v0.2 常驻调度预留，默认仍是项目根。"""
    custom = _write_creds(tmp_path / "elsewhere.json")
    monkeypatch.setenv("BRAIN_CREDENTIALS_PATH", str(custom))
    assert creds_mod.load(project_root=tmp_path / "nonexistent").email == "someone@example.com"


def test_文件缺失时报错明确且不含凭据内容(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_CREDENTIALS_PATH", raising=False)
    with pytest.raises(AuthError) as excinfo:
        creds_mod.load(project_root=tmp_path)
    message = str(excinfo.value)
    assert ".brain_credentials" in message
    assert SECRET not in message


def test_格式错误时报错不回显文件内容(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_CREDENTIALS_PATH", raising=False)
    (tmp_path / ".brain_credentials").write_text(json.dumps({"password": SECRET}), encoding="utf-8")
    with pytest.raises(AuthError) as excinfo:
        creds_mod.load(project_root=tmp_path)
    assert SECRET not in str(excinfo.value)


def test_凭据对象的_repr_不泄露密码(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_CREDENTIALS_PATH", raising=False)
    _write_creds(tmp_path / ".brain_credentials")
    assert SECRET not in repr(creds_mod.load(project_root=tmp_path))


# --- config ---------------------------------------------------------------


def test_默认值与设计一致():
    cfg = config_mod.load(project_root=None, env={})
    assert cfg.classify_threshold == 0.3
    assert cfg.correlation_threshold == 0.7
    assert cfg.correlation_threshold_source == "convention_demo"
    assert cfg.split_threshold == 9000
    assert cfg.page_size == 100
    assert cfg.batch_size == 20


def test_配置文件覆盖默认值_环境变量再覆盖配置文件(tmp_path):
    (tmp_path / "alpha-platform.json").write_text(
        json.dumps({"classify_threshold": 0.4, "page_size": 500}), encoding="utf-8"
    )
    cfg = config_mod.load(project_root=tmp_path, env={"ALPHA_PLATFORM_PAGE_SIZE": "250"})
    assert cfg.classify_threshold == 0.4   # 来自配置文件
    assert cfg.page_size == 250            # 环境变量胜出


def test_手工指定相关性阈值时来源标记为_manual(tmp_path):
    (tmp_path / "alpha-platform.json").write_text(
        json.dumps({"correlation_threshold": 0.65}), encoding="utf-8"
    )
    cfg = config_mod.load(project_root=tmp_path, env={})
    assert cfg.correlation_threshold == 0.65
    assert cfg.correlation_threshold_source == "manual"

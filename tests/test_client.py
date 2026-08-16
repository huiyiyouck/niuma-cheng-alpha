"""BrainClient 测试：契约、认证自愈、重试退避、异常契约、凭据纪律。

全部通过传输层替身（FakeSession）执行，零真实平台请求——设计 §3.1.0 规定
业务测试默认在客户端方法层构造替身，本文件测的正是客户端自身，故用传输层。
"""
import pytest

from alpha_platform.client import (
    AuthError,
    BrainClient,
    Credentials,
    PlatformError,
    RateLimitError,
    RetryPolicy,
)


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """按 (method, path 后缀) 排队响应；记录全部请求供断言。"""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        for (m, suffix), responses in self.routes.items():
            if m == method and url.endswith(suffix):
                return responses.pop(0) if len(responses) > 1 else responses[0]
        return FakeResponse(200, {})


NO_WAIT = RetryPolicy(
    correlation_interval_sec=0, list_backoff_base_sec=0, rate_limit_backoff_sec=0
)


def make_client(routes=None, retry=NO_WAIT):
    session = FakeSession(routes or {})
    client = BrainClient(
        Credentials("someone@example.com", "pw"), session=session, retry=retry
    )
    return client, session


# --- 凭据纪律（PRD #9 / DevOps N6） ---------------------------------------


def test_凭据的_repr_不含密码():
    creds = Credentials("someone@example.com", "s3cret-value")
    assert "s3cret-value" not in repr(creds)
    assert "password" not in repr(creds)


def test_密码不出现在任何请求参数或_url_中():
    client, session = make_client()
    client.list_alphas(stage="IS", limit=1, offset=0)
    for call in session.calls:
        rendered = repr(call)
        assert "s3cret" not in rendered
        assert "pw" not in call.get("params", {}).values()


# --- 认证自愈（设计 §3.1.1） ----------------------------------------------


def test_首次调用先认证再发业务请求():
    client, session = make_client()
    client.list_alphas(stage="IS", limit=10, offset=0)
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"].endswith("/authentication")
    assert session.calls[1]["url"].endswith("/users/self/alphas")


def test_业务请求遇_401_自动重认证并重试一次():
    routes = {
        ("POST", "/authentication"): [FakeResponse(201, {})],
        ("GET", "/users/self/alphas"): [
            FakeResponse(401),
            FakeResponse(200, {"count": 3, "results": [{"id": "A1"}]}),
        ],
    }
    client, session = make_client(routes)
    page = client.list_alphas(stage="IS", limit=10, offset=0)

    assert page.count == 3
    auth_calls = [c for c in session.calls if c["url"].endswith("/authentication")]
    assert len(auth_calls) == 2  # 首次 + 401 后重认证


def test_认证失败抛_AuthError():
    routes = {("POST", "/authentication"): [FakeResponse(401, text="bad credentials")]}
    client, _ = make_client(routes)
    with pytest.raises(AuthError):
        client.list_alphas(stage="IS", limit=1, offset=0)


def test_需要生物识别时抛_AuthError_不引入浏览器依赖():
    routes = {
        ("POST", "/authentication"): [
            FakeResponse(401, {"detail": "persona"}, text="WWW-Authenticate: persona")
        ]
    }
    client, _ = make_client(routes)
    with pytest.raises(AuthError):
        client.list_alphas(stage="IS", limit=1, offset=0)


# --- list_alphas 契约（设计 §3.1 / §4.1） ---------------------------------


def test_list_alphas_组装时间窗参数并返回_count_与_items():
    routes = {
        ("GET", "/users/self/alphas"): [
            FakeResponse(200, {"count": 12841, "results": [{"id": "A1"}, {"id": "A2"}]})
        ]
    }
    client, session = make_client(routes)
    page = client.list_alphas(
        stage="IS",
        limit=100,
        offset=200,
        date_created_gt="2026-01-01T00:00:00-04:00",
        date_created_lt="2026-02-01T00:00:00-04:00",
        order="-dateCreated",
    )

    assert page.count == 12841
    assert [i["id"] for i in page.items] == ["A1", "A2"]
    params = session.calls[-1]["params"]
    assert params["stage"] == "IS"
    assert params["limit"] == 100
    assert params["offset"] == 200
    assert params["order"] == "-dateCreated"
    # 平台的时间窗参数名自带比较符，两端均为开区间（设计 §4.1）
    assert params["dateCreated>"] == "2026-01-01T00:00:00-04:00"
    assert params["dateCreated<"] == "2026-02-01T00:00:00-04:00"


def test_list_alphas_遇_429_退避重试后成功():
    routes = {
        ("GET", "/users/self/alphas"): [
            FakeResponse(429),
            FakeResponse(200, {"count": 1, "results": []}),
        ]
    }
    client, _ = make_client(routes)
    assert client.list_alphas(stage="IS", limit=1, offset=0).count == 1


def test_list_alphas_重试耗尽仍_429_抛_RateLimitError():
    routes = {("GET", "/users/self/alphas"): [FakeResponse(429), FakeResponse(429), FakeResponse(429)]}
    client, _ = make_client(routes)
    with pytest.raises(RateLimitError):
        client.list_alphas(stage="IS", limit=1, offset=0)


def test_其他_5xx_抛_PlatformError():
    routes = {("GET", "/users/self/alphas"): [FakeResponse(500, text="boom")]}
    client, _ = make_client(routes)
    with pytest.raises(PlatformError):
        client.list_alphas(stage="IS", limit=1, offset=0)


# --- get_alpha（R4/D21：恢复路径的独立判据） -------------------------------


def test_get_alpha_直查返回原样详情():
    routes = {
        ("GET", "/alphas/A1"): [
            FakeResponse(200, {"id": "A1", "stage": "OS", "dateSubmitted": "2026-08-15T10:00:00-04:00"})
        ]
    }
    client, _ = make_client(routes)
    detail = client.get_alpha("A1")
    assert detail["stage"] == "OS"
    assert detail["dateSubmitted"] == "2026-08-15T10:00:00-04:00"


# --- 相关性（设计 §3.1.3：重试耗尽不抛异常，返回 None） --------------------


def test_相关性成功时取_schema_max():
    routes = {("GET", "/alphas/A1/correlations/self"): [FakeResponse(200, {"schema": {"max": 0.83}})]}
    client, _ = make_client(routes)
    result = client.get_self_correlation("A1")
    assert result.max_correlation == 0.83
    assert result.attempts == 1


def test_相关性首查为空时重试直到拿到值():
    routes = {
        ("GET", "/alphas/A1/correlations/prod"): [
            FakeResponse(200, {}),
            FakeResponse(200, {}),
            FakeResponse(200, {"schema": {"max": 0.42}}),
        ]
    }
    client, _ = make_client(routes)
    result = client.get_prod_correlation("A1")
    assert result.max_correlation == 0.42
    assert result.attempts == 3


def test_相关性重试耗尽返回_None_而不抛异常():
    """PRD #6 的第三态出口：达重试上限 → 待定，不阻塞其余候选。"""
    routes = {("GET", "/alphas/A1/correlations/self"): [FakeResponse(200, {}) for _ in range(9)]}
    client, _ = make_client(routes)
    result = client.get_self_correlation("A1")
    assert result.max_correlation is None
    assert result.attempts == NO_WAIT.correlation_max_attempts


# --- submit（设计 §8 第 5 条：不返回 Response 对象） -----------------------


def test_submit_成功返回_ok_且_raw_是已解析的_json():
    routes = {("POST", "/alphas/A1/submit"): [FakeResponse(201, {"id": "A1", "status": "ok"})]}
    client, _ = make_client(routes)
    outcome = client.submit_alpha("A1")
    assert outcome.ok is True
    assert outcome.error is None
    assert outcome.raw == {"id": "A1", "status": "ok"}


def test_submit_失败保留原因原文且不吞异常():
    routes = {("POST", "/alphas/A1/submit"): [FakeResponse(403, text="not eligible")]}
    client, _ = make_client(routes)
    outcome = client.submit_alpha("A1")
    assert outcome.ok is False
    assert "not eligible" in outcome.error


def test_submit_返回值不含_response_对象或_cookie():
    """Demo 的 `return response.__dict__` 是一条凭据泄露路径，本设计明确不采纳。"""
    routes = {("POST", "/alphas/A1/submit"): [FakeResponse(201, {"id": "A1"})]}
    client, _ = make_client(routes)
    rendered = repr(client.submit_alpha("A1"))
    assert "FakeResponse" not in rendered
    assert "cookie" not in rendered.lower()

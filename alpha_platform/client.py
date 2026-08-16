"""BrainClient —— 全项目唯一 HTTP 出口（设计 §3.1）。

除本模块外任何模块不得直接发起 HTTP 请求：这是 PRD #5 / #6 / #8 / #9 能在
不触达真实平台的前提下自动验证的唯一前提。

凭据纪律（PRD #9）：密码只入内存、`repr=False`、不写回任何文件、不进日志；
日志采用白名单式记录（方法名 / alpha_id / 状态码），而非「记录全部再脱敏」。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.worldquantbrain.com"


@dataclass(frozen=True)
class Credentials:
    email: str
    # repr=False 是契约的一部分：封堵白名单式日志管不到的泄露路径
    # （未捕获异常的 traceback、logging.exception、调试器打印局部变量）。
    password: str = field(repr=False)


@dataclass(frozen=True)
class AlphaListPage:
    count: int          # 平台对该查询条件报告的总数
    items: list[dict]   # 原样 JSON 列表项


@dataclass(frozen=True)
class CorrelationResult:
    max_correlation: float | None   # None = 重试耗尽仍无数据
    attempts: int
    raw: dict | None


@dataclass(frozen=True)
class SubmitOutcome:
    ok: bool
    error: str | None   # 失败原因原文，不吞异常
    raw: dict | None    # 已解析的 JSON body，绝不是 Response 对象（设计 §8 第 5 条）


@dataclass(frozen=True)
class RetryPolicy:
    """参数来自 Demo 实测，均可配——这些是平台行为的观测值，不是常量。"""

    correlation_max_attempts: int = 5
    correlation_interval_sec: float = 20.0   # 固定间隔，无退避递增
    list_max_attempts: int = 3
    list_backoff_base_sec: float = 2.0       # 指数退避 ×1.5
    rate_limit_backoff_sec: float = 30.0


class AuthError(RuntimeError):
    """凭据缺失 / 认证失败 / 需生物识别——立即终止，退出码 2。"""


class RateLimitError(RuntimeError):
    """HTTP 429 或平台并发限制；退避重试耗尽后抛出，断点保留。"""


class PlatformError(RuntimeError):
    """其他 4xx/5xx；记录并中止当前条目，不影响其余条目。"""


class BrainClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._credentials = credentials
        self._session = session if session is not None else requests.Session()
        self._base_url = base_url.rstrip("/")
        self._retry = retry or RetryPolicy()
        self._authenticated = False

    # --- 公开契约 ---------------------------------------------------------

    def list_alphas(
        self,
        *,
        stage: str,
        limit: int,
        offset: int,
        date_created_gt: str | None = None,
        date_created_lt: str | None = None,
        order: str = "dateCreated",
    ) -> AlphaListPage:
        params: dict[str, object] = {
            "stage": stage,
            "limit": limit,
            "offset": offset,
            "order": order,
        }
        # 平台的时间窗参数名自带比较符，两端均为开区间（设计 §4.1）
        if date_created_gt is not None:
            params["dateCreated>"] = date_created_gt
        if date_created_lt is not None:
            params["dateCreated<"] = date_created_lt

        body = self._request_json(
            "GET",
            "/users/self/alphas",
            params=params,
            max_attempts=self._retry.list_max_attempts,
        )
        if "count" not in body:
            # A15：「取不到总数」与「总数为 0」必须区分。默认成 0 会让 sync 的
            # `while offset < reported` 直接不进循环，整窗数据静默丢失，而
            # fetched == reported == 0 让窗口级对账仍判绿——不确定就报错，不猜。
            raise PlatformError("列表响应缺少 count 字段，无法判定该窗口总数")
        return AlphaListPage(count=body["count"], items=body.get("results", []))

    def get_alpha(self, alpha_id: str) -> dict:
        """按 ID 直查单条详情（R4/D21）。

        供 `submit --reconcile` 取平台真实状态：判据必须绕开本地库与水位逻辑，
        恢复路径不该依赖那条可能已经出问题的常规写入链。
        """
        return self._request_json(
            "GET", f"/alphas/{alpha_id}", max_attempts=self._retry.list_max_attempts
        )

    def get_self_correlation(self, alpha_id: str) -> CorrelationResult:
        return self._correlation(f"/alphas/{alpha_id}/correlations/self")

    def get_prod_correlation(self, alpha_id: str) -> CorrelationResult:
        return self._correlation(f"/alphas/{alpha_id}/correlations/prod")

    def submit_alpha(self, alpha_id: str) -> SubmitOutcome:
        """唯一不可逆动作。失败不抛异常，把原因原文交回上层记录。

        例外是限流：429 表示平台**未受理**该请求（无副作用），把它写成
        「提交失败」终态会让该记录从此不在提交清单里——一个暂时状态被固化。
        故 429 退避重试，耗尽则抛 `RateLimitError` 交由上层中止批次、保留断点（A22）。
        """
        self._ensure_authenticated()
        for attempt in range(1, self._retry.list_max_attempts + 1):
            response = self._send("POST", f"/alphas/{alpha_id}/submit")
            if response.status_code == 401:
                self._authenticate()
                response = self._send("POST", f"/alphas/{alpha_id}/submit")
            if response.status_code != 429:
                break
            if attempt == self._retry.list_max_attempts:
                raise RateLimitError(
                    f"提交 {alpha_id} 触发限流，重试 {attempt} 次仍未受理；该条保持可重试状态"
                )
            time.sleep(self._retry.rate_limit_backoff_sec)

        logger.info("submit_alpha alpha_id=%s status=%s", alpha_id, response.status_code)
        if 200 <= response.status_code < 300:
            return SubmitOutcome(ok=True, error=None, raw=_json_or_none(response))
        return SubmitOutcome(
            ok=False,
            error=f"HTTP {response.status_code}: {response.text}",
            raw=_json_or_none(response),
        )

    # --- 内部实现 ---------------------------------------------------------

    def _correlation(self, path: str) -> CorrelationResult:
        """平台异步计算，首查常返空——重试到拿到值或耗尽。

        重试耗尽**不抛异常**，返回 max_correlation=None，由 precheck 判为「待定」
        （设计 §3.1.3）：一条候选查不到，不该炸掉整批。
        """
        last_body: dict | None = None
        for attempt in range(1, self._retry.correlation_max_attempts + 1):
            body = self._request_json(
                "GET", path, max_attempts=self._retry.list_max_attempts
            )
            last_body = body
            value = _extract_max_correlation(body)
            if value is not None:
                return CorrelationResult(max_correlation=value, attempts=attempt, raw=body)
            if attempt < self._retry.correlation_max_attempts:
                time.sleep(self._retry.correlation_interval_sec)

        return CorrelationResult(
            max_correlation=None,
            attempts=self._retry.correlation_max_attempts,
            raw=last_body,
        )

    def _request_json(
        self, method: str, path: str, *, params: dict | None = None, max_attempts: int
    ) -> dict:
        self._ensure_authenticated()
        backoff = self._retry.list_backoff_base_sec

        for attempt in range(1, max_attempts + 1):
            response = self._send(method, path, params=params)
            logger.info("%s %s status=%s", method, path, response.status_code)

            if response.status_code == 401:
                # 认证自愈：长任务中途 session 失效时按需重认证
                self._authenticate()
                continue
            if response.status_code == 429:
                if attempt == max_attempts:
                    raise RateLimitError(f"{method} {path} 触发限流，重试 {max_attempts} 次仍未通过")
                time.sleep(self._retry.rate_limit_backoff_sec)
                continue
            if response.status_code >= 400:
                raise PlatformError(f"{method} {path} 返回 HTTP {response.status_code}: {response.text}")

            return _json_or_none(response) or {}

        raise PlatformError(f"{method} {path} 重试 {max_attempts} 次仍未取得响应")

    def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            self._authenticate()

    def _authenticate(self) -> None:
        response = self._session.request(
            "POST",
            f"{self._base_url}/authentication",
            auth=(self._credentials.email, self._credentials.password),
        )
        if response.status_code == 401 and "persona" in (response.text or ""):
            raise AuthError(
                "平台要求生物识别验证（persona）——v0.1 不实现浏览器分支，请手工在平台完成验证后重试"
            )
        if response.status_code >= 400:
            raise AuthError(f"认证失败：HTTP {response.status_code}")
        self._authenticated = True
        logger.info("authenticated status=%s", response.status_code)

    def _send(self, method: str, path: str, *, params: dict | None = None):
        return self._session.request(method, f"{self._base_url}{path}", params=params)


def _extract_max_correlation(body: dict | None) -> float | None:
    """相关性响应的最大值：`schema.max` 优先，顶层 `max` 兜底（A18）。

    Demo 的 `check_correlation` 写了多层兜底，说明平台响应格式存在变体。只认一层
    的后果不是报错，而是把「格式不同」误判为「平台还没算完」→ 重试耗尽 → 假待定：
    白等 80 秒、占一个 `--retry-pending` 名额、Owner 以为是平台慢。
    """
    if not body:
        return None
    for value in ((body.get("schema") or {}).get("max"), body.get("max")):
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _json_or_none(response) -> dict | None:
    try:
        body = response.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None

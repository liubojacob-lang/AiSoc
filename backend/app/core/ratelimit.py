"""Redis sliding-window rate limiting (middleware).

Buckets: global per-identity (user sub / api key / ip), plus stricter buckets
on auth and AI routes. Fail-open on Redis unavailability — availability beats
strict limiting for a SOC tool, and login has account lockout as a second
line. The tradeoff is documented in the completion report.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("ratelimit")

_lua_sliding = """
-- 时钟源用 Redis 服务端 TIME：免疫客户端（尤其 WSL2 VM）时钟漂移，
-- 漂移曾导致滑动窗口无法排空、限流卡死（Docker 首跑实测）。
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window * 1000)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now .. '-' .. count .. '-' .. math.random())
    redis.call('PEXPIRE', key, window * 1000)
    return {1, limit - count - 1}
end
return {0, 0}
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client=None) -> None:
        super().__init__(app)
        self.redis = redis_client
        self._script_sha: str | None = None
        self._disabled = False

    def _identity(self, request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            import jwt as pyjwt

            try:
                payload = pyjwt.decode(
                    auth[7:],
                    settings.effective_jwt_secret(),
                    algorithms=[settings.jwt_algorithm],
                    options={"verify_exp": False},
                )
                return f"user:{payload.get('sub', '?')}"
            except pyjwt.PyJWTError:
                pass
        api_key = request.headers.get("x-api-key", "")
        if api_key:
            import hashlib

            return "key:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"

    def _limits(self, path: str) -> list[tuple[str, int, int]]:
        """(scope_name, limit, window_seconds)"""
        limits = [("global", settings.rl_global_per_min, 60)]
        if path.endswith("/auth/login"):
            limits.append(("login", settings.rl_login_per_min, 60))
        if "/retry-triage" in path or path.endswith("/ask"):
            limits.append(("ai", settings.rl_ai_per_hour, 3600))
        return limits

    async def _allow(self, identity: str, scope: str, limit: int, window_s: int) -> bool:
        if self._disabled or self.redis is None:
            return True
        key = f"rl:{scope}:{identity}"
        try:
            if self._script_sha is None:
                self._script_sha = await self.redis.script_load(_lua_sliding)
            # 时钟源在 Lua 内取 Redis TIME；窗口传秒（Lua 内统一 ×1000 转 ms）
            allowed, _remaining = await self.redis.evalsha(
                self._script_sha, 1, key, window_s, limit
            )
            return bool(int(allowed))
        except Exception as e:  # noqa: BLE001 - fail-open, logged once per burst
            self._disabled = True
            log.warning("rate_limiter_disabled", error=str(e))
            return True

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(settings.api_prefix) or path in (
            f"{settings.api_prefix}/healthz",
            f"{settings.api_prefix}/readyz",
        ):
            return await call_next(request)
        identity = self._identity(request)
        for scope, limit, window in self._limits(path):
            if not await self._allow(identity, scope, limit, window):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate.limited",
                            "message": "too many requests",
                            "request_id": "-",
                            "details": {"scope": scope},
                        }
                    },
                    headers={"Retry-After": str(window)},
                )
        return await call_next(request)

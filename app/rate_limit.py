from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.config import Settings


TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = capacity / tonumber(ARGV[2])
local now_parts = redis.call('TIME')
local now = now_parts[1] * 1000 + math.floor(now_parts[2] / 1000)
local values = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(values[1]) or capacity
local updated_at = tonumber(values[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - updated_at) * refill_per_ms)
local allowed = 0
local retry_ms = 0
if tokens >= 1 then
  allowed = 1
  tokens = tokens - 1
else
  retry_ms = math.ceil((1 - tokens) / refill_per_ms)
end
redis.call('HSET', key, 'tokens', tokens, 'updated_at', now)
redis.call('PEXPIRE', key, math.ceil(tonumber(ARGV[2]) * 2))
return {allowed, math.floor(tokens), retry_ms}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter:
    def __init__(self, settings: Settings, redis_client: Any = None):
        self.settings = settings
        self._redis = redis_client
        self._memory: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def check(self, subject: str, policy: str, limit: int) -> RateLimitResult:
        if self.settings.rate_limit_backend == "disabled":
            return RateLimitResult(True, limit, limit, 0)
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        key = f"rag:ratelimit:{policy}:{digest}"
        if self.settings.rate_limit_backend == "redis":
            return self._check_redis(key, limit)
        return self._check_memory(key, limit)

    def _check_redis(self, key: str, limit: int) -> RateLimitResult:
        try:
            result = self._client().eval(
                TOKEN_BUCKET_SCRIPT,
                1,
                key,
                limit,
                self.settings.rate_limit_window_seconds * 1000,
            )
        except Exception as exc:
            raise RuntimeError("Rate-limit service is unavailable") from exc
        return RateLimitResult(
            allowed=bool(int(result[0])),
            limit=limit,
            remaining=max(0, int(result[1])),
            retry_after=max(0, math.ceil(int(result[2]) / 1000)),
        )

    def _check_memory(self, key: str, limit: int) -> RateLimitResult:
        now = time.monotonic()
        window = self.settings.rate_limit_window_seconds
        refill_per_second = limit / window
        with self._lock:
            tokens, updated_at = self._memory.get(key, (float(limit), now))
            tokens = min(float(limit), tokens + max(0.0, now - updated_at) * refill_per_second)
            if tokens >= 1:
                tokens -= 1
                self._memory[key] = (tokens, now)
                return RateLimitResult(True, limit, int(tokens), 0)
            self._memory[key] = (tokens, now)
            return RateLimitResult(
                False,
                limit,
                0,
                max(1, math.ceil((1 - tokens) / refill_per_second)),
            )

    def _client(self):
        if self._redis is None:
            try:
                import redis
            except ImportError as exc:  # pragma: no cover - server extra supplies it
                raise RuntimeError("Redis client is unavailable") from exc
            self._redis = redis.Redis.from_url(
                self.settings.redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=False,
            )
        return self._redis

    def health(self) -> bool:
        if self.settings.rate_limit_backend != "redis":
            return True
        try:
            return bool(self._client().ping())
        except Exception:
            return False

"""Small Redis-backed fixed-window limiter. Authentication fails closed if Redis is unavailable."""
from __future__ import annotations

from fastapi import HTTPException, Request
import redis

from .config import settings


def limit(namespace: str, maximum: int, window_seconds: int):
    def enforce(request: Request) -> None:
        client_id = request.client.host if request.client else "unknown"
        key = f"backupforge:ratelimit:{namespace}:{client_id}"
        try:
            client = redis.Redis.from_url(settings().redis_url, socket_connect_timeout=1, socket_timeout=1)
            with client.pipeline() as pipeline:
                pipeline.incr(key)
                pipeline.expire(key, window_seconds, nx=True)
                count, _ = pipeline.execute()
        except redis.RedisError:
            raise HTTPException(503, "authentication temporarily unavailable")
        if count > maximum:
            raise HTTPException(429, "too many requests; retry later")
    return enforce

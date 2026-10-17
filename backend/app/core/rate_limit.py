"""Sliding window Rate Limiter per TECH_REQUIREMENTS.md §9 and API_SPEC.md §Ops."""

import hashlib
import logging
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter tracking requests per minute."""

    def __init__(self, limit_per_minute: int = 60) -> None:
        self.limit = limit_per_minute
        # Dict of key -> list of timestamp floats
        self._history: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_limit: int | None = None) -> tuple[bool, int, int]:
        """Checks if a request is permitted under the sliding 60-second window.

        Returns: (is_allowed, remaining_quota, reset_seconds)
        """
        effective_limit = max_limit or self.limit
        now = time.time()
        window_start = now - 60.0

        # Prune timestamps older than 60 seconds
        timestamps = self._history[key]
        valid_timestamps = [t for t in timestamps if t > window_start]
        self._history[key] = valid_timestamps

        count = len(valid_timestamps)
        if count >= effective_limit:
            oldest = valid_timestamps[0]
            reset_seconds = max(1, int(oldest + 60.0 - now))
            return False, 0, reset_seconds

        # Record this request
        valid_timestamps.append(now)
        remaining = max(0, effective_limit - len(valid_timestamps))
        reset_seconds = 60
        return True, remaining, reset_seconds

    def reset(self, key: str | None = None) -> None:
        """Clears rate limit history (used in test fixtures)."""
        if key:
            self._history.pop(key, None)
        else:
            self._history.clear()


# Global in-memory rate limiter singleton
rate_limiter = SlidingWindowRateLimiter(limit_per_minute=settings.RATE_LIMIT_PER_MINUTE)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI Middleware enforcing rate limiting across all API endpoints."""

    # Paths exempt from rate limits
    EXEMPT_PATHS = {
        "/health",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/static",
        "/favicon.ico",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)  # type: ignore[no-any-return]

        path = request.url.path
        # Skip exempt paths or static assets
        if any(path == ep or path.startswith(f"{ep}/") for ep in self.EXEMPT_PATHS):
            return await call_next(request)  # type: ignore[no-any-return]

        # Extract identifier: user_id from auth header or client host IP
        auth_header = request.headers.get("Authorization", "")
        identifier: str
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            # Hash full token to generate distinct per-user bucket
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
            identifier = f"token:{token_hash}"
        else:
            client_host = request.client.host if request.client else "unknown_ip"
            identifier = f"ip:{client_host}"

        allowed, remaining, reset_seconds = rate_limiter.is_allowed(
            identifier, max_limit=settings.RATE_LIMIT_PER_MINUTE
        )

        if not allowed:
            logger.warning("Rate limit exceeded for %s on %s", identifier, path)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": (
                            f"Rate limit of {settings.RATE_LIMIT_PER_MINUTE} req/min "
                            f"exceeded. Please retry in {reset_seconds}s."
                        ),
                    }
                },
                headers={
                    "Retry-After": str(reset_seconds),
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_PER_MINUTE),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                },
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)
        return response

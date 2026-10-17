"""Observability & Tracing Adapter (Langfuse + Local) per TECH_REQUIREMENTS.md §6."""

import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class TraceSpan:
    """Represents an execution span within an observability trace."""

    def __init__(
        self,
        name: str,
        span_id: str,
        trace_id: str,
        start_time: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.span_id = span_id
        self.trace_id = trace_id
        self.start_time = start_time
        self.end_time: float | None = None
        self.duration_ms: float = 0.0
        self.metadata = metadata or {}
        self.output: Any = None
        self.error: str | None = None

    def end(self, output: Any = None, error: str | None = None) -> None:
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 2)
        self.output = output
        self.error = error


class ObservabilityTrace:
    """Represents a high-level trace tracking a complete user request."""

    def __init__(
        self,
        name: str,
        trace_id: str,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.trace_id = trace_id
        self.user_id = user_id
        self.session_id = session_id
        self.tags = tags or []
        self.metadata = metadata or {}
        self.start_time = time.time()
        self.end_time: float | None = None
        self.duration_ms: float = 0.0
        self.spans: list[TraceSpan] = []
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0

    def start_span(self, name: str, metadata: dict[str, Any] | None = None) -> TraceSpan:
        span = TraceSpan(
            name=name,
            span_id=str(uuid.uuid4())[:8],
            trace_id=self.trace_id,
            start_time=time.time(),
            metadata=metadata,
        )
        self.spans.append(span)
        return span

    def end(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 2)
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens


class ObservabilityAdapter(ABC):
    """Abstract interface for application tracing and LLM observability."""

    @abstractmethod
    def create_trace(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObservabilityTrace:
        """Initializes and returns a new trace context."""
        pass

    @abstractmethod
    def log_trace(self, trace: ObservabilityTrace) -> None:
        """Flushes and persists trace information."""
        pass

    @abstractmethod
    def get_recent_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        """Returns recent captured trace payloads."""
        pass


class LocalObservabilityAdapter(ObservabilityAdapter):
    """In-memory and structured JSON log observability adapter for development and testing."""

    def __init__(self, max_buffer_size: int = 200) -> None:
        self.max_buffer_size = max_buffer_size
        self._traces: list[dict[str, Any]] = []

    def create_trace(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObservabilityTrace:
        trace_id = str(uuid.uuid4())
        return ObservabilityTrace(
            name=name,
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            metadata=metadata,
        )

    def log_trace(self, trace: ObservabilityTrace) -> None:
        if not settings.ENABLE_TRACING:
            return

        payload = {
            "trace_id": trace.trace_id,
            "name": trace.name,
            "user_id": trace.user_id,
            "session_id": trace.session_id,
            "tags": trace.tags,
            "duration_ms": trace.duration_ms,
            "prompt_tokens": trace.prompt_tokens,
            "completion_tokens": trace.completion_tokens,
            "total_tokens": trace.prompt_tokens + trace.completion_tokens,
            "spans_count": len(trace.spans),
            "spans": [
                {
                    "name": s.name,
                    "span_id": s.span_id,
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                }
                for s in trace.spans
            ],
            "metadata": trace.metadata,
        }
        self._traces.append(payload)
        if len(self._traces) > self.max_buffer_size:
            self._traces.pop(0)

        logger.info(
            "TRACE [%s] '%s': %.1f ms | Tokens: %d | Spans: %d",
            trace.trace_id[:8],
            trace.name,
            trace.duration_ms,
            trace.prompt_tokens + trace.completion_tokens,
            len(trace.spans),
        )

    def get_recent_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(self._traces[-limit:]))


class LangfuseObservabilityAdapter(ObservabilityAdapter):
    """Production Langfuse adapter using langfuse SDK when credentials are provided."""

    def __init__(self) -> None:
        self.fallback = LocalObservabilityAdapter()
        self.langfuse_client: Any = None

        if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
            try:
                from langfuse import Langfuse  # type: ignore[import-not-found]

                self.langfuse_client = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_HOST,
                )
                logger.info("Langfuse observability client initialized successfully.")
            except ImportError:
                logger.info("langfuse package not installed, using structured local tracing.")
            except Exception as e:
                logger.warning("Failed to initialize Langfuse: %s", e)

    def create_trace(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObservabilityTrace:
        return self.fallback.create_trace(name, user_id, session_id, tags, metadata)

    def log_trace(self, trace: ObservabilityTrace) -> None:
        self.fallback.log_trace(trace)
        if self.langfuse_client:
            try:
                self.langfuse_client.trace(
                    id=trace.trace_id,
                    name=trace.name,
                    user_id=trace.user_id,
                    session_id=trace.session_id,
                    tags=trace.tags,
                    metadata=trace.metadata,
                )
            except Exception as e:
                logger.warning("Error forwarding trace to Langfuse: %s", e)

    def get_recent_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.fallback.get_recent_traces(limit)


_obs_instance: ObservabilityAdapter | None = None


def get_observability_adapter() -> ObservabilityAdapter:
    """Returns singleton observability adapter instance."""
    global _obs_instance
    if _obs_instance is None:
        if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
            _obs_instance = LangfuseObservabilityAdapter()
        else:
            _obs_instance = LocalObservabilityAdapter()
    return _obs_instance

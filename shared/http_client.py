"""
Shared HTTP client helper used by the Coordinator (and any agent that calls
another agent) to dispatch AgentMessage envelopes with a bounded timeout and
limited retry. This is the ONE place timeout/retry policy lives, per the
cross-cutting requirement that it not be duplicated per-service.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from .auth import API_KEY, API_KEY_HEADER
from .schema import ActionStatus, AgentMessage, AgentResponse

logger = logging.getLogger("agent_client")

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_ATTEMPTS = 2


def ping_health(base_url: str, timeout: float = 2.0) -> dict[str, Any]:
    """Ping an agent's /health endpoint. Never raises -- returns a status dict."""
    start = time.perf_counter()
    try:
        resp = httpx.get(f"{base_url}/health", timeout=timeout)
        duration_ms = (time.perf_counter() - start) * 1000
        if resp.status_code == 200:
            return {"up": True, "response_time_ms": round(duration_ms, 1), "detail": resp.json()}
        return {"up": False, "response_time_ms": round(duration_ms, 1), "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, must never raise
        duration_ms = (time.perf_counter() - start) * 1000
        return {"up": False, "response_time_ms": round(duration_ms, 1), "detail": str(exc)}


def dispatch(
    base_url: str,
    message: AgentMessage,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> AgentResponse:
    """
    Send an AgentMessage to an agent's /invoke endpoint with bounded timeout
    and limited retry. On persistent failure/timeout, returns a synthetic
    AgentResponse with status=UNAVAILABLE instead of raising -- callers
    (the Coordinator's orchestration loop) must be able to continue the
    workflow when an agent cannot be reached.
    """
    last_error: Optional[str] = None
    last_status = ActionStatus.UNAVAILABLE

    for attempt in range(1, max_attempts + 1):
        message.attempt = attempt
        start = time.perf_counter()
        try:
            resp = httpx.post(
                f"{base_url}/invoke",
                json=message.model_dump(),
                headers={API_KEY_HEADER: API_KEY},
                timeout=timeout,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            if resp.status_code == 200:
                data = resp.json()
                data["duration_ms"] = round(duration_ms, 1)
                return AgentResponse(**data)
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            last_status = ActionStatus.ERROR
            logger.warning(
                "dispatch attempt %d/%d to %s failed: %s [correlation_id=%s]",
                attempt, max_attempts, message.recipient, last_error, message.correlation_id,
            )
        except httpx.TimeoutException as exc:
            last_error = f"timeout after {timeout}s: {exc}"
            last_status = ActionStatus.TIMEOUT
            logger.warning(
                "dispatch attempt %d/%d to %s timed out [correlation_id=%s]",
                attempt, max_attempts, message.recipient, message.correlation_id,
            )
        except httpx.RequestError as exc:
            last_error = f"connection error: {exc}"
            last_status = ActionStatus.UNAVAILABLE
            logger.warning(
                "dispatch attempt %d/%d to %s unreachable: %s [correlation_id=%s]",
                attempt, max_attempts, message.recipient, exc, message.correlation_id,
            )

    return AgentResponse(
        incident_id=message.incident_id,
        task_id=message.task_id,
        correlation_id=message.correlation_id,
        sender=message.recipient,
        recipient=message.sender,
        action=message.action,
        status=last_status,
        result={},
        error=last_error or "unknown error",
    )

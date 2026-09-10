"""
Shared inter-agent message contract.

Every agent-to-agent call (Coordinator -> Agent, and Agent -> Coordinator response)
uses AgentMessage as the envelope. The `payload` field carries action-specific data
and is intentionally typed as a free-form dict so each agent can define its own
request/response shapes without the shared schema needing to know about them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class AgentName(str, Enum):
    COORDINATOR = "coordinator-agent"
    RAG = "quality-rag-agent"
    TRACEABILITY = "traceability-agent"
    PROCESS_MAINTENANCE = "process-maintenance-agent"
    LOGISTICS = "logistics-agent"
    FRONTEND = "frontend"
    HUMAN = "human"


class ActionStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class AgentMessage(BaseModel):
    """Core message envelope used for every inter-agent REST call."""

    incident_id: str
    task_id: str = Field(default_factory=lambda: new_id("TASK"))
    correlation_id: str
    sender: str
    recipient: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "quality-manager"
    timestamp: str = Field(default_factory=now_iso)

    # retry / dedup support
    attempt: int = 1
    max_attempts: int = 3


class AgentResponse(BaseModel):
    """Standard response envelope every agent returns for an AgentMessage."""

    incident_id: str
    task_id: str
    correlation_id: str
    sender: str
    recipient: str
    action: str
    status: ActionStatus
    result: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    timestamp: str = Field(default_factory=now_iso)
    duration_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# Valid action values per agent (documented in MESSAGE_CONTRACT.md as a table)
# ---------------------------------------------------------------------------

VALID_ACTIONS: dict[str, list[str]] = {
    AgentName.RAG.value: [
        "retrieve_requirements",
    ],
    AgentName.TRACEABILITY.value: [
        "identify_suspect_population",
    ],
    AgentName.PROCESS_MAINTENANCE.value: [
        "analyze_process_deviations",
        "execute_work_order",
    ],
    AgentName.LOGISTICS.value: [
        "assess_containment",
        "execute_containment_action",
        "release_containment_action",
    ],
}


class ExtractedIncident(BaseModel):
    """Structured extraction of a free-text OEM complaint (Coordinator LLM call)."""

    customer: str
    part_number: str
    symptom: str
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    urgency: str = "medium"
    raw_complaint: str = ""


class ProposedAction(BaseModel):
    """An operational action proposed by an agent, held for human approval."""

    action_id: str = Field(default_factory=lambda: new_id("ACT"))
    action_type: str  # inventory_hold | shipment_block | 100_percent_sort | work_order | oem_notification | 8d_update | release_material
    description: str
    owner_agent: str
    target: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.AWAITING_APPROVAL
    rationale: str = ""

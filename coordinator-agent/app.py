"""
Incident Coordinator Agent.

Accepts a free-text OEM complaint, extracts structured fields via LLM,
dynamically selects which agents to call, dispatches over REST with
timeout/retry, consolidates findings into the four UI categories, holds
all operational actions pending human approval, and generates the initial
8D draft.
"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.audit import get_events, log_event  # noqa: E402
from shared.auth import verify_api_key  # noqa: E402
from shared.dedup import TaskDedupStore  # noqa: E402
from shared.http_client import DEFAULT_MAX_ATTEMPTS, DEFAULT_TIMEOUT_SECONDS, dispatch  # noqa: E402
from shared.schema import AgentMessage, AgentName, new_id, now_iso  # noqa: E402

from consolidation import consolidate  # noqa: E402
from eightd import build_8d  # noqa: E402
from extraction import extract_incident  # noqa: E402
from orchestration import AGENT_URLS, run_workflow  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("coordinator-agent")

SERVICE_NAME = AgentName.COORDINATOR.value

app = FastAPI(title="Incident Coordinator Agent")
submission_dedup = TaskDedupStore()  # dedupe on request_id (frontend-supplied idempotency key)

# In-memory incident store. NOT persisted across restarts -- acceptable
# simplification for this take-home; see README "Known Limitations".
INCIDENTS: dict[str, dict] = {}


@app.get("/health")
def health():
    return {"service": SERVICE_NAME, "status": "ok", "incidents_tracked": len(INCIDENTS)}


class SubmitComplaintRequest(BaseModel):
    complaint_text: str
    requested_by: str = "quality-manager"
    request_id: Optional[str] = None  # idempotency key so a UI double-submit doesn't re-run the workflow


@app.post("/submit_complaint", dependencies=[Depends(verify_api_key)])
def submit_complaint(req: SubmitComplaintRequest):
    if req.request_id:
        cached = submission_dedup.get(req.request_id)
        if cached is not None:
            logger.info("Duplicate request_id %s detected, returning cached incident bundle", req.request_id)
            return cached

    incident_id = new_id("OEM-INC")
    correlation_id = f"CORR-{uuid.uuid4().hex[:8].upper()}"

    log_event(
        correlation_id=correlation_id, event_type="incident_received", incident_id=incident_id,
        sender="frontend", recipient=SERVICE_NAME, status="received",
        detail={"complaint_text": req.complaint_text, "requested_by": req.requested_by},
    )

    incident = extract_incident(req.complaint_text)
    log_event(
        correlation_id=correlation_id, event_type="extraction_complete", incident_id=incident_id,
        sender=SERVICE_NAME, recipient=SERVICE_NAME, status="ok", detail=incident.model_dump(),
    )

    workflow_result = run_workflow(incident_id, correlation_id, incident, req.requested_by)

    consolidated = consolidate(incident, workflow_result["selected_agents"], workflow_result["agent_responses"])

    draft_8d = build_8d(
        incident_id, correlation_id, incident, workflow_result["selected_agents"],
        workflow_result["agent_responses"], consolidated, consolidated["proposed_actions"],
    )

    bundle = {
        "incident_id": incident_id,
        "correlation_id": correlation_id,
        "requested_by": req.requested_by,
        "created_at": now_iso(),
        "extracted_incident": incident.model_dump(),
        "selected_agents": workflow_result["selected_agents"],
        "selection_reasons": workflow_result["selection_reasons"],
        "agent_health": workflow_result["agent_health"],
        "agent_responses": workflow_result["agent_responses"],
        "consolidated": consolidated,
        "proposed_actions": consolidated["proposed_actions"],
        "draft_8d": draft_8d,
    }
    INCIDENTS[incident_id] = bundle

    log_event(
        correlation_id=correlation_id, event_type="workflow_complete", incident_id=incident_id,
        sender=SERVICE_NAME, recipient="frontend", status="ok",
        detail={"selected_agents": workflow_result["selected_agents"]},
    )

    if req.request_id:
        submission_dedup.put(req.request_id, bundle)

    return bundle


@app.get("/incident/{incident_id}", dependencies=[Depends(verify_api_key)])
def get_incident(incident_id: str):
    bundle = INCIDENTS.get(incident_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident_id {incident_id}")
    return bundle


@app.get("/incident/{incident_id}/8d", dependencies=[Depends(verify_api_key)])
def get_8d(incident_id: str):
    bundle = INCIDENTS.get(incident_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident_id {incident_id}")
    from shared.schema import ExtractedIncident

    incident = ExtractedIncident(**bundle["extracted_incident"])
    fresh_8d = build_8d(
        incident_id, bundle["correlation_id"], incident, bundle["selected_agents"],
        bundle["agent_responses"], bundle["consolidated"], bundle["proposed_actions"],
    )
    bundle["draft_8d"] = fresh_8d
    return fresh_8d


@app.get("/audit/{correlation_id}", dependencies=[Depends(verify_api_key)])
def get_audit(correlation_id: str):
    return get_events(correlation_id=correlation_id)


class ApproveActionRequest(BaseModel):
    incident_id: str
    ref_id: str
    approved: bool
    modification_note: Optional[str] = None
    approved_by: str = "quality-manager"


AGENT_ACTION_FOR_TYPE = {
    "work_order": ("execute_work_order", "work_order_id"),
    "inventory_hold": ("execute_containment_action", "action_id"),
    "shipment_block": ("execute_containment_action", "action_id"),
    "100_percent_sort": ("execute_containment_action", "action_id"),
    "release_material": ("release_containment_action", "action_id"),
}

# Action types that release previously-executed material back to shippable
# status once approved -- proposed dynamically (see approve_action below)
# rather than at initial consolidation, since they only make sense after
# the underlying hold has actually been executed.
RELEASABLE_ACTION_TYPES = {"inventory_hold"}


@app.post("/approve_action", dependencies=[Depends(verify_api_key)])
def approve_action(req: ApproveActionRequest):
    bundle = INCIDENTS.get(req.incident_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident_id {req.incident_id}")

    action = next((a for a in bundle["proposed_actions"] if a["ref_id"] == req.ref_id), None)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Unknown action ref_id {req.ref_id}")

    correlation_id = bundle["correlation_id"]

    if req.modification_note:
        action["description"] = f"{action['description']} [Modified by {req.approved_by}: {req.modification_note}]"
        action["modification_note"] = req.modification_note

    log_event(
        correlation_id=correlation_id, event_type="approval_decision", incident_id=req.incident_id,
        sender="frontend", recipient=SERVICE_NAME, action=action["action_type"],
        status="approved" if req.approved else "rejected",
        detail={"ref_id": req.ref_id, "approved_by": req.approved_by, "modification_note": req.modification_note},
    )

    if action["agent"] == AgentName.COORDINATOR.value:
        # Coordinator-native action (oem_notification, 8d_update) -- no downstream
        # agent call needed, but it still only executes after this explicit
        # human approval step.
        action["status"] = "executed" if req.approved else "rejected"
    else:
        agent_action, id_field = AGENT_ACTION_FOR_TYPE.get(action["action_type"], (None, None))
        if agent_action is None:
            raise HTTPException(status_code=400, detail=f"No executable mapping for action_type {action['action_type']}")
        # A release_material action targets the ORIGINAL held command's ref_id
        # (stored on the release proposal at creation time), not its own ref_id.
        target_ref_id = action.get("releases_ref_id", req.ref_id)
        message = AgentMessage(
            incident_id=req.incident_id, correlation_id=correlation_id, sender=SERVICE_NAME,
            recipient=action["agent"], action=agent_action,
            payload={id_field: target_ref_id, "approved": req.approved}, requested_by=req.approved_by,
        )
        response = dispatch(AGENT_URLS[action["agent"]], message, timeout=DEFAULT_TIMEOUT_SECONDS, max_attempts=DEFAULT_MAX_ATTEMPTS)
        log_event(
            correlation_id=correlation_id, event_type="execution_response", incident_id=req.incident_id,
            sender=response.sender, recipient=SERVICE_NAME, action=agent_action, status=response.status.value,
            detail={"result": response.result, "error": response.error},
        )
        if response.status.value == "ok" or response.result.get("status") in ("executed", "released", "rejected"):
            action["status"] = response.result.get("status", "rejected" if not req.approved else "approved")
        else:
            action["status"] = "unavailable"
            action["error"] = response.error

    if action["status"] in ("executed", "released"):
        bundle["consolidated"]["human_approved_actions"].append(
            {
                "category": "Human-Approved Action",
                "source": action["agent"],
                "text": action["description"],
                "action_type": action["action_type"],
                "approved_by": req.approved_by,
            }
        )

    # Once material is genuinely put on hold, propose a follow-on
    # release_material action (also approval-gated) so the human-approval
    # loop covers "Release previously contained material" per the
    # Human Approval Examples list -- not proposable earlier, since it only
    # makes sense once a hold has actually been executed.
    if action["status"] == "executed" and action["action_type"] in RELEASABLE_ACTION_TYPES:
        already_proposed = any(a.get("releases_ref_id") == action["ref_id"] for a in bundle["proposed_actions"])
        if not already_proposed:
            release_action = {
                "agent": action["agent"],
                "ref_id": new_id("ACT"),
                "action_type": "release_material",
                "description": (
                    f"Release previously-contained material for approved {action['action_type']} "
                    f"(ref {action['ref_id']}) back to shippable status, once root cause is confirmed resolved."
                ),
                "status": "awaiting_approval",
                "priority": "Low",
                "releases_ref_id": action["ref_id"],
            }
            bundle["proposed_actions"].append(release_action)
            log_event(
                correlation_id=correlation_id, event_type="release_action_proposed", incident_id=req.incident_id,
                sender=SERVICE_NAME, recipient="frontend", action="release_material", status="awaiting_approval",
                detail={"ref_id": release_action["ref_id"], "releases_ref_id": action["ref_id"]},
            )

    log_event(
        correlation_id=correlation_id, event_type="action_status_update", incident_id=req.incident_id,
        sender=SERVICE_NAME, recipient="frontend", action=action["action_type"], status=action["status"],
        detail={"ref_id": req.ref_id},
    )

    return action

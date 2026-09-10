"""
Hand-written orchestration for the Incident Coordinator: parse request ->
select agents -> call them over REST -> merge results. No orchestration
framework is used, per the take-home's constraints.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.audit import log_event  # noqa: E402
from shared.http_client import DEFAULT_MAX_ATTEMPTS, DEFAULT_TIMEOUT_SECONDS, dispatch, ping_health  # noqa: E402
from shared.schema import ActionStatus, AgentMessage, AgentName, AgentResponse, ExtractedIncident, new_id  # noqa: E402

logger = logging.getLogger("coordinator.orchestration")

AGENT_URLS: dict[str, str] = {
    AgentName.RAG.value: os.environ.get("RAG_AGENT_URL", "http://quality-rag-agent:8001"),
    AgentName.TRACEABILITY.value: os.environ.get("TRACEABILITY_AGENT_URL", "http://traceability-agent:8002"),
    AgentName.PROCESS_MAINTENANCE.value: os.environ.get("PROCESS_MAINTENANCE_AGENT_URL", "http://process-maintenance-agent:8003"),
    AgentName.LOGISTICS.value: os.environ.get("LOGISTICS_AGENT_URL", "http://logistics-agent:8004"),
}

ALWAYS_ON_AGENTS = [AgentName.RAG.value, AgentName.TRACEABILITY.value]


def select_agents(incident: ExtractedIncident) -> tuple[list[str], dict[str, str]]:
    """
    Dynamic agent selection: RAG and Traceability always run. Process/Maintenance
    and Logistics are selected based on simple heuristics derived from the
    extracted incident (urgency + symptom keywords), per the take-home's
    dynamic-selection requirement. Returns (selected_agents, reason_per_agent).
    """
    selected = list(ALWAYS_ON_AGENTS)
    reasons = {
        AgentName.RAG.value: "Always consulted for applicable customer requirements, control plan, and PFMEA guidance.",
        AgentName.TRACEABILITY.value: "Always consulted to identify the suspect production population for the complaint's date range.",
    }

    symptom_lower = (incident.symptom or "").lower()
    urgency_high = incident.urgency in ("high", "critical")

    process_keywords = ["intermittent", "connector", "electrical", "calibration", "assembly", "press", "torque"]
    if urgency_high or any(k in symptom_lower for k in process_keywords):
        selected.append(AgentName.PROCESS_MAINTENANCE.value)
        matched = [k for k in process_keywords if k in symptom_lower]
        reasons[AgentName.PROCESS_MAINTENANCE.value] = (
            f"Selected: urgency='{incident.urgency}'" + (f", symptom matched keyword(s) {matched}" if matched else "")
            + " -- suggests a process/hardware root cause worth checking against control-plan limits."
        )

    logistics_keywords = ["field", "vehicle", "shipped", "warranty", "dealer", "recall"]
    if urgency_high or any(k in symptom_lower for k in logistics_keywords):
        selected.append(AgentName.LOGISTICS.value)
        matched = [k for k in logistics_keywords if k in symptom_lower]
        reasons[AgentName.LOGISTICS.value] = (
            f"Selected: urgency='{incident.urgency}'" + (f", symptom matched keyword(s) {matched}" if matched else "")
            + " -- potential shipped/field-affected product requires containment quantity assessment."
        )

    return selected, reasons


def check_agent_health(selected_agents: list[str]) -> dict[str, dict]:
    health = {}
    for agent in selected_agents:
        health[agent] = ping_health(AGENT_URLS[agent])
    return health


def _build_message(incident_id: str, correlation_id: str, recipient: str, action: str, payload: dict, requested_by: str) -> AgentMessage:
    return AgentMessage(
        incident_id=incident_id,
        correlation_id=correlation_id,
        sender=AgentName.COORDINATOR.value,
        recipient=recipient,
        action=action,
        payload=payload,
        requested_by=requested_by,
    )


def _dispatch_and_log(base_url: str, message: AgentMessage) -> AgentResponse:
    log_event(
        correlation_id=message.correlation_id, event_type="dispatch", incident_id=message.incident_id,
        task_id=message.task_id, sender=message.sender, recipient=message.recipient, action=message.action,
        status="sent", detail={"payload_keys": list(message.payload.keys())},
    )
    response = dispatch(base_url, message, timeout=DEFAULT_TIMEOUT_SECONDS, max_attempts=DEFAULT_MAX_ATTEMPTS)
    log_event(
        correlation_id=message.correlation_id, event_type="response", incident_id=message.incident_id,
        task_id=message.task_id, sender=response.sender, recipient=response.recipient, action=response.action,
        status=response.status.value, detail={"error": response.error, "duration_ms": response.duration_ms},
    )
    return response


def run_workflow(incident_id: str, correlation_id: str, incident: ExtractedIncident, requested_by: str) -> dict:
    """
    Two-phase dispatch:
      Phase 1 (always-on): RAG + Traceability run first.
      Phase 2 (conditional): Process/Maintenance and Logistics, if selected, are
      scoped using Traceability's suspect-population output so their findings
      are targeted rather than generic -- this is the "merge results" step of
      the hand-written orchestration feeding forward into the next dispatch.
    """
    selected_agents, selection_reasons = select_agents(incident)
    agent_health = check_agent_health(selected_agents)
    agent_responses: dict[str, AgentResponse] = {}

    # --- Phase 1: always-on agents ---
    rag_query = f"{incident.symptom} {incident.part_number} requirements control plan PFMEA"
    rag_msg = _build_message(
        incident_id, correlation_id, AgentName.RAG.value, "retrieve_requirements",
        {"query": rag_query, "symptom": incident.symptom, "top_k": 5}, requested_by,
    )
    agent_responses[AgentName.RAG.value] = _dispatch_and_log(AGENT_URLS[AgentName.RAG.value], rag_msg)

    trace_msg = _build_message(
        incident_id, correlation_id, AgentName.TRACEABILITY.value, "identify_suspect_population",
        {
            "part_number": incident.part_number,
            "date_range_start": incident.date_range_start,
            "date_range_end": incident.date_range_end,
        },
        requested_by,
    )
    agent_responses[AgentName.TRACEABILITY.value] = _dispatch_and_log(AGENT_URLS[AgentName.TRACEABILITY.value], trace_msg)

    trace_result = agent_responses[AgentName.TRACEABILITY.value].result or {}
    suspect_pop = trace_result.get("suspect_population")

    # --- Phase 2: conditional agents, scoped by Phase 1 findings ---
    if AgentName.PROCESS_MAINTENANCE.value in selected_agents:
        pm_payload = {
            "date_range_start": incident.date_range_start,
            "date_range_end": incident.date_range_end,
        }
        if suspect_pop:
            pm_payload.update(
                line=suspect_pop.get("line"),
                shift=suspect_pop.get("shift"),
                connector_lot=suspect_pop.get("connector_lot"),
            )
        pm_msg = _build_message(
            incident_id, correlation_id, AgentName.PROCESS_MAINTENANCE.value, "analyze_process_deviations",
            pm_payload, requested_by,
        )
        agent_responses[AgentName.PROCESS_MAINTENANCE.value] = _dispatch_and_log(
            AGENT_URLS[AgentName.PROCESS_MAINTENANCE.value], pm_msg
        )

    if AgentName.LOGISTICS.value in selected_agents:
        log_payload = {"part_number": incident.part_number}
        if suspect_pop:
            log_payload.update(
                suspect_serial_numbers=suspect_pop.get("serial_numbers", []),
                suspect_count=suspect_pop.get("count", 0),
                containment_boundary_description=trace_result.get("recommended_containment_boundary", ""),
            )
        else:
            log_payload.update(suspect_serial_numbers=[], suspect_count=0, containment_boundary_description="")
        log_msg = _build_message(
            incident_id, correlation_id, AgentName.LOGISTICS.value, "assess_containment", log_payload, requested_by,
        )
        agent_responses[AgentName.LOGISTICS.value] = _dispatch_and_log(AGENT_URLS[AgentName.LOGISTICS.value], log_msg)

    return {
        "selected_agents": selected_agents,
        "selection_reasons": selection_reasons,
        "agent_health": agent_health,
        # mode="json" ensures enum fields (e.g. status) serialize to plain
        # strings everywhere downstream, not raw Enum members.
        "agent_responses": {k: v.model_dump(mode="json") for k, v in agent_responses.items()},
    }

"""
Consolidates raw agent responses into the four UI-facing categories
(Retrieved Requirement / Manufacturing-Data Finding / Agent Hypothesis /
Human-Approved Action), surfaces cross-agent conflicts, lists evidence
gaps, and builds the merged list of proposed operational actions awaiting
human approval.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.schema import ActionStatus, AgentName, ExtractedIncident, new_id  # noqa: E402


def _agent_ok(agent_responses: dict, agent_name: str) -> bool:
    r = agent_responses.get(agent_name)
    return bool(r) and r.get("status") == ActionStatus.OK.value


def build_proposed_actions(agent_responses: dict, incident: ExtractedIncident) -> list[dict]:
    actions: list[dict] = []

    pm = agent_responses.get(AgentName.PROCESS_MAINTENANCE.value, {}).get("result", {}) or {}
    wo = pm.get("proposed_work_order")
    if wo:
        actions.append(
            {
                "agent": AgentName.PROCESS_MAINTENANCE.value,
                "ref_id": wo["work_order_id"],
                "action_type": "work_order",
                "description": wo["description"],
                "status": wo.get("status", "awaiting_approval"),
                "priority": wo.get("priority", "Medium"),
            }
        )

    logi = agent_responses.get(AgentName.LOGISTICS.value, {}).get("result", {}) or {}
    for cmd in logi.get("proposed_actions", []) or []:
        actions.append(
            {
                "agent": AgentName.LOGISTICS.value,
                "ref_id": cmd["action_id"],
                "action_type": cmd["action_type"],
                "description": cmd["description"],
                "status": cmd.get("status", "awaiting_approval"),
                "priority": "High",
            }
        )

    # Coordinator-native actions (no downstream agent owns these -- approval
    # directly flips their status since there's no specialized comms agent
    # in this system's scope).
    actions.append(
        {
            "agent": AgentName.COORDINATOR.value,
            "ref_id": new_id("ACT"),
            "action_type": "oem_notification",
            "description": (
                f"Notify {incident.customer} Supplier Quality of suspect population, containment boundary, "
                f"and preliminary findings for {incident.part_number} per CSR Section 5 (24-hour notification "
                "requirement)."
            ),
            "status": "awaiting_approval",
            "priority": "High" if incident.urgency in ("high", "critical") else "Medium",
        }
    )
    actions.append(
        {
            "agent": AgentName.COORDINATOR.value,
            "ref_id": new_id("ACT"),
            "action_type": "8d_update",
            "description": f"Submit interim 8D (D1-D3) to {incident.customer} Supplier Quality within the 3-day requirement.",
            "status": "awaiting_approval",
            "priority": "Medium",
        }
    )

    return actions


def detect_conflicts(agent_responses: dict) -> list[dict]:
    conflicts = []

    rag = agent_responses.get(AgentName.RAG.value, {}).get("result", {}) or {}
    trace = agent_responses.get(AgentName.TRACEABILITY.value, {}).get("result", {}) or {}

    rag_evidence = (rag.get("evidence") or []) + (rag.get("pfmea_control_plan_findings") or [])
    firmware_precedent = any(
        "8d report" in e.get("document", "").lower() and "firmware" in e.get("content", "").lower()
        for e in rag_evidence
    )
    fw_analysis = trace.get("firmware_analysis") or []
    fw_spread = 0.0
    if fw_analysis:
        rates = [r["bad_rate"] for r in fw_analysis]
        fw_spread = max(rates) - min(rates)

    disproportionate_found = trace.get("disproportionate_segment_found")
    common_factor = trace.get("common_factor") or ""

    if firmware_precedent and disproportionate_found and fw_spread < 0.10:
        conflicts.append(
            {
                "description": (
                    "RAG retrieved a historical 8D report (OEM-INC-2023-041) whose root cause was a firmware "
                    "logic defect for a similar intermittent steering-warning-lamp symptom -- suggesting "
                    "firmware as a plausible cause by precedent. However, current Traceability data shows "
                    f"only a {fw_spread:.0%} EOL bad-rate spread across firmware versions in this window "
                    "(not a differentiating factor), and instead identifies a strong line/shift/component-lot "
                    f"pattern ({common_factor}). These two signals point to different root causes and should "
                    "be explicitly reconciled -- do not assume this is a repeat of the 2023 firmware issue "
                    "without confirming connector/contact-resistance findings, per the prior 8D's own "
                    "Lessons Learned."
                ),
                "sources": [AgentName.RAG.value, AgentName.TRACEABILITY.value],
            }
        )
    elif firmware_precedent and not disproportionate_found:
        conflicts.append(
            {
                "description": (
                    "RAG surfaced a historical firmware-related root cause for a similar symptom, but "
                    "Traceability did not identify a disproportionate production segment in this window -- "
                    "the firmware hypothesis cannot currently be confirmed or ruled out from production data "
                    "alone."
                ),
                "sources": [AgentName.RAG.value, AgentName.TRACEABILITY.value],
            }
        )

    return conflicts


def build_evidence_gaps(agent_responses: dict, selected_agents: list[str]) -> list[str]:
    gaps = []
    for agent in [AgentName.RAG.value, AgentName.TRACEABILITY.value, AgentName.PROCESS_MAINTENANCE.value, AgentName.LOGISTICS.value]:
        if agent not in selected_agents:
            gaps.append(f"{agent} was not selected for this incident (see routing decision) -- no findings available from this source.")
            continue
        r = agent_responses.get(agent)
        if not r or r.get("status") != ActionStatus.OK.value:
            gaps.append(f"{agent} did not return usable results (status={r.get('status') if r else 'no response'}); its findings are marked unavailable.")

    rag_result = agent_responses.get(AgentName.RAG.value, {}).get("result", {}) or {}
    if rag_result.get("no_evidence_found"):
        gaps.append("No supporting evidence was found in the controlled document set for the RAG query -- requirements applicability should be manually reviewed by Quality Engineering.")

    trace_result = agent_responses.get(AgentName.TRACEABILITY.value, {}).get("result", {}) or {}
    if trace_result and not trace_result.get("disproportionate_segment_found"):
        gaps.append("Traceability did not identify a statistically disproportionate production segment -- root cause may not be process-related, or the affected population extends beyond simple line/shift/lot grouping.")

    return gaps


def consolidate(incident: ExtractedIncident, selected_agents: list[str], agent_responses: dict) -> dict:
    rag = agent_responses.get(AgentName.RAG.value, {}).get("result", {}) or {}
    trace = agent_responses.get(AgentName.TRACEABILITY.value, {}).get("result", {}) or {}
    pm = agent_responses.get(AgentName.PROCESS_MAINTENANCE.value, {}).get("result", {}) or {}
    logi = agent_responses.get(AgentName.LOGISTICS.value, {}).get("result", {}) or {}

    # --- Category 1: Retrieved Requirement ---
    retrieved_requirements = []
    for e in (rag.get("evidence") or []):
        retrieved_requirements.append({**e, "category": "Retrieved Requirement", "kind": "general"})
    for e in (rag.get("pfmea_control_plan_findings") or []):
        retrieved_requirements.append({**e, "category": "Retrieved Requirement", "kind": "pfmea_control_plan"})

    # --- Category 2: Manufacturing-Data Finding ---
    manufacturing_data_findings = []
    if trace.get("common_factor"):
        manufacturing_data_findings.append(
            {"category": "Manufacturing-Data Finding", "source": AgentName.TRACEABILITY.value, "text": trace["common_factor"]}
        )
    for dev in (pm.get("deviations") or []):
        manufacturing_data_findings.append(
            {
                "category": "Manufacturing-Data Finding",
                "source": AgentName.PROCESS_MAINTENANCE.value,
                "text": f"Machine {dev['machine_id']}: {dev['units_out_of_spec']}/{dev['units_checked']} units "
                        f"({dev['out_of_spec_pct']:.0%}) out of spec on {dev['parameter']} "
                        f"({dev['spec_limits']['min']}-{dev['spec_limits']['max']}{dev['spec_limits']['unit']}).",
            }
        )
    if logi.get("affected_by_location"):
        loc = logi["affected_by_location"]
        manufacturing_data_findings.append(
            {
                "category": "Manufacturing-Data Finding",
                "source": AgentName.LOGISTICS.value,
                "text": f"Suspect units by location -- Tier-1 Plant: {loc['tier1_plant']['estimated_suspect_units_on_hand']}, "
                        f"In-Transit: {loc['in_transit']['suspect_units']}, "
                        f"Delivered (OEM/Warehouse): {loc['delivered_to_oem_or_warehouse']['suspect_units']}.",
            }
        )

    # --- Category 3: Agent Hypothesis ---
    agent_hypotheses = []
    if rag.get("interpretation"):
        agent_hypotheses.append({"category": "Agent Hypothesis", "source": AgentName.RAG.value, "text": rag["interpretation"]})
    if trace.get("reasoning"):
        agent_hypotheses.append({"category": "Agent Hypothesis", "source": AgentName.TRACEABILITY.value, "text": trace["reasoning"]})
    for rec in (pm.get("diagnostic_recommendations") or []):
        agent_hypotheses.append({"category": "Agent Hypothesis", "source": AgentName.PROCESS_MAINTENANCE.value, "text": rec["recommendation"]})

    conflicts = detect_conflicts(agent_responses)
    evidence_gaps = build_evidence_gaps(agent_responses, selected_agents)
    proposed_actions = build_proposed_actions(agent_responses, incident)

    complaint_summary = (
        f"{incident.customer} reported '{incident.symptom}' for part {incident.part_number}, "
        f"urgency={incident.urgency}, date range {incident.date_range_start} to {incident.date_range_end}."
    )

    recommended_containment = [a["description"] for a in proposed_actions if a["agent"] != AgentName.COORDINATOR.value]

    return {
        "complaint_summary": complaint_summary,
        "retrieved_requirements": retrieved_requirements,
        "manufacturing_data_findings": manufacturing_data_findings,
        "agent_hypotheses": agent_hypotheses,
        "human_approved_actions": [],  # populated as actions are approved/executed
        "conflicts": conflicts,
        "evidence_gaps": evidence_gaps,
        "recommended_containment": recommended_containment,
        "suspect_quantity_by_location": logi.get("affected_by_location"),
        "suspect_population": trace.get("suspect_population"),
        "proposed_actions": proposed_actions,
    }

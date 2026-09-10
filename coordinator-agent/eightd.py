"""
Builds the initial 8D draft entirely from data already collected during the
run (extraction + agent responses + consolidated findings + current
proposed-action approval state) -- no new analysis logic here, per the
take-home's "auto-generate from data already collected" instruction.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.schema import AgentName, ExtractedIncident  # noqa: E402


def build_8d(
    incident_id: str,
    correlation_id: str,
    incident: ExtractedIncident,
    selected_agents: list[str],
    agent_responses: dict,
    consolidated: dict,
    proposed_actions: list[dict],
) -> dict:
    trace = agent_responses.get(AgentName.TRACEABILITY.value, {}).get("result", {}) or {}
    logi = agent_responses.get(AgentName.LOGISTICS.value, {}).get("result", {}) or {}
    suspect_pop = trace.get("suspect_population")

    d1_team = [f"{a} (automated agent)" for a in selected_agents] + ["Human Quality Manager (approval authority)"]

    approved_actions = [a for a in proposed_actions if a["status"] in ("approved", "executed", "released")]

    affected_part_numbers = [incident.part_number]
    suspect_quantities = {
        "total_suspect_units": suspect_pop["count"] if suspect_pop else 0,
        "by_location": consolidated.get("suspect_quantity_by_location"),
    }

    return {
        "incident_id": incident_id,
        "correlation_id": correlation_id,
        "generated_at_note": "Auto-generated from collected agent findings; regenerate after further approvals to refresh D6/D7-adjacent sections.",
        "D1_team": d1_team,
        "D2_problem_description": {
            "customer": incident.customer,
            "part_number": incident.part_number,
            "symptom": incident.symptom,
            "raw_complaint": incident.raw_complaint,
            "urgency": incident.urgency,
        },
        "D3_interim_containment": consolidated.get("recommended_containment", []),
        "D4_preliminary_causes_and_gaps": {
            "hypotheses": [h["text"] for h in consolidated.get("agent_hypotheses", [])],
            "conflicts_to_reconcile": [c["description"] for c in consolidated.get("conflicts", [])],
            "evidence_gaps": consolidated.get("evidence_gaps", []),
        },
        "affected_part_numbers": affected_part_numbers,
        "suspect_quantities": suspect_quantities,
        "traceability_range": {
            "date_range_used": trace.get("date_range_used"),
            "containment_boundary": trace.get("recommended_containment_boundary"),
        },
        "customer_communication_summary": (
            f"Draft notification to {incident.customer} Supplier Quality: suspect population of "
            f"{suspect_pop['count'] if suspect_pop else 'TBD'} units identified "
            f"({trace.get('recommended_containment_boundary', 'boundary pending traceability analysis')}); "
            "interim containment actions proposed and pending/receiving approval; root cause investigation "
            "ongoing per D4."
        ),
        "D5_D6_D7_status": "Not yet started -- pending root cause confirmation and effectiveness verification (out of scope for this initial draft).",
        "approved_actions": [
            {"action_type": a["action_type"], "description": a["description"], "owner_agent": a["agent"], "status": a["status"]}
            for a in approved_actions
        ],
    }

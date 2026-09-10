"""
Streamlit frontend for the Supplier Quality Copilot.

Talks to the Incident Coordinator Agent over REST. Renders, in order:
complaint input -> extracted incident -> routing decision -> agent health
-> retrieved requirements -> traceability results -> suspect quantities by
location -> preliminary cause hypotheses (+ surfaced conflicts) ->
recommended containment -> per-action approve/reject/modify controls ->
initial 8D -> audit/message history.

Four categories (Retrieved Requirement / Manufacturing-Data Finding /
Agent Hypothesis / Human-Approved Action) are color/icon-tagged everywhere
they appear via `category_badge()`.
"""
from __future__ import annotations

import os
import uuid

import pandas as pd
import requests
import streamlit as st

COORDINATOR_URL = os.environ.get("COORDINATOR_URL", "http://localhost:8000")
API_KEY = os.environ.get("SHARED_API_KEY", "dev-shared-secret-change-me")
HEADERS = {"X-API-Key": API_KEY}
TIMEOUT = 30

st.set_page_config(page_title="Supplier Quality Copilot", layout="wide")

CATEGORY_STYLE = {
    "Retrieved Requirement": {"emoji": "\U0001F4D8", "color": "#1a73e8", "label": "Retrieved Requirement"},
    "Manufacturing-Data Finding": {"emoji": "\U0001F3ED", "color": "#188038", "label": "Manufacturing-Data Finding"},
    "Agent Hypothesis": {"emoji": "\U0001F9E9", "color": "#e8710a", "label": "Agent Hypothesis"},
    "Human-Approved Action": {"emoji": "✅", "color": "#188038", "label": "Human-Approved Action"},
}


def category_badge(category: str) -> str:
    s = CATEGORY_STYLE.get(category, {"emoji": "•", "color": "#666", "label": category})
    return (
        f"<span style='background:{s['color']}1a;color:{s['color']};padding:2px 8px;"
        f"border-radius:10px;font-size:0.78em;font-weight:600;border:1px solid {s['color']}55;'>"
        f"{s['emoji']} {s['label']}</span>"
    )


# --------------------------------------------------------------------------
# API helpers
# --------------------------------------------------------------------------

def api_post(path: str, payload: dict) -> dict | None:
    try:
        resp = requests.post(f"{COORDINATOR_URL}{path}", json=payload, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.error(f"Request to coordinator failed ({path}): {exc}")
        return None


def api_get(path: str) -> dict | None:
    try:
        resp = requests.get(f"{COORDINATOR_URL}{path}", headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.error(f"Request to coordinator failed ({path}): {exc}")
        return None


def refresh_bundle():
    incident_id = st.session_state.get("incident_id")
    if incident_id:
        fresh = api_get(f"/incident/{incident_id}")
        if fresh is not None:
            st.session_state["bundle"] = fresh


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### Supplier Quality Copilot")
    st.caption("Automotive Tier-1 multi-agent OEM complaint investigation")
    st.markdown("---")
    st.markdown(f"**Coordinator:** `{COORDINATOR_URL}`")
    try:
        h = requests.get(f"{COORDINATOR_URL}/health", timeout=5).json()
        st.success(f"Coordinator up ({h.get('incidents_tracked', 0)} incidents tracked)")
    except Exception:
        st.error("Coordinator unreachable")
    st.markdown("---")
    st.markdown("**Category legend**")
    for cat in CATEGORY_STYLE:
        st.markdown(category_badge(cat), unsafe_allow_html=True)
    st.markdown("---")
    if st.button("Start New Complaint"):
        st.session_state.pop("bundle", None)
        st.session_state.pop("incident_id", None)
        st.rerun()

st.title("Supplier Quality Copilot")
st.caption(
    "Investigate an OEM quality complaint across controlled documents (RAG), production traceability, "
    "process/maintenance data, and logistics/containment -- with mandatory human approval before any "
    "operational action."
)

# --------------------------------------------------------------------------
# 1. Complaint input
# --------------------------------------------------------------------------

st.header("1. Submit OEM Complaint")
with st.form("complaint_form"):
    complaint_text = st.text_area(
        "Complaint / command text",
        value=st.session_state.get(
            "last_complaint_text",
            "Northbridge Motors is reporting intermittent steering warning lamp illumination on EPS-2200-A "
            "modules, urgent safety concern. Vehicles built between 2025-05-08 and 2025-05-18. Several units "
            "have already shipped to the assembly plant.",
        ),
        height=110,
    )
    requested_by = st.text_input("Requested by", value="quality-manager")
    submitted = st.form_submit_button("Submit Complaint", type="primary")

if submitted and complaint_text.strip():
    st.session_state["last_complaint_text"] = complaint_text
    with st.spinner("Extracting incident details and dispatching to agents..."):
        bundle = api_post(
            "/submit_complaint",
            {"complaint_text": complaint_text, "requested_by": requested_by, "request_id": str(uuid.uuid4())},
        )
    if bundle is not None:
        st.session_state["bundle"] = bundle
        st.session_state["incident_id"] = bundle["incident_id"]
        st.success(f"Incident {bundle['incident_id']} created (correlation_id={bundle['correlation_id']}).")

bundle = st.session_state.get("bundle")
if bundle is None:
    st.info("Submit a complaint above to begin an investigation.")
    st.stop()

incident = bundle["extracted_incident"]
consolidated = bundle["consolidated"]
agent_responses = bundle["agent_responses"]

# --------------------------------------------------------------------------
# 2. Extracted incident details
# --------------------------------------------------------------------------

st.header("2. Extracted Incident Details")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Customer", incident["customer"])
c2.metric("Part Number", incident["part_number"])
c3.metric("Urgency", incident["urgency"].upper())
c4.metric("Date Range", f"{incident['date_range_start']} to {incident['date_range_end']}")
c5.metric("Incident ID", bundle["incident_id"])
st.markdown(f"**Symptom:** {incident['symptom']}")
st.caption(f"correlation_id: `{bundle['correlation_id']}`")

# --------------------------------------------------------------------------
# 3. Selected agents + routing decision
# --------------------------------------------------------------------------

st.header("3. Selected Agents & Routing Decision")
for agent in bundle["selected_agents"]:
    reason = bundle["selection_reasons"].get(agent, "")
    st.markdown(f"- **{agent}** -- {reason}")
not_selected = [a for a in ["process-maintenance-agent", "logistics-agent"] if a not in bundle["selected_agents"]]
if not_selected:
    st.caption(f"Not selected for this incident: {', '.join(not_selected)}")

# --------------------------------------------------------------------------
# 4. Agent status panel
# --------------------------------------------------------------------------

st.header("4. Agent Status Panel")
health_cols = st.columns(len(bundle["agent_health"]) or 1)
for i, (agent, h) in enumerate(bundle["agent_health"].items()):
    with health_cols[i % len(health_cols)]:
        icon = "\U0001F7E2" if h.get("up") else "\U0001F534"
        st.markdown(f"{icon} **{agent}**")
        st.caption(f"{h.get('response_time_ms', '?')} ms")

# --------------------------------------------------------------------------
# 5. Retrieved source passages
# --------------------------------------------------------------------------

st.header("5. Retrieved Source Passages")
retrieved = consolidated.get("retrieved_requirements", [])
if not retrieved:
    st.warning("No supporting evidence found for this query in the controlled document set.")
else:
    for item in retrieved:
        st.markdown(category_badge("Retrieved Requirement"), unsafe_allow_html=True)
        st.markdown(f"**{item['document']}** -- *{item['section']}*  (relevance: {item['relevance']})")
        st.markdown(f"> {item['content'][:500]}{'...' if len(item['content']) > 500 else ''}")
        st.markdown("")

rag_result = agent_responses.get("quality-rag-agent", {}).get("result", {})
if rag_result.get("interpretation"):
    st.markdown(category_badge("Agent Hypothesis"), unsafe_allow_html=True)
    st.markdown(f"*RAG interpretation:* {rag_result['interpretation']}")

# --------------------------------------------------------------------------
# 6. Traceability results
# --------------------------------------------------------------------------

st.header("6. Traceability Results")
trace_result = agent_responses.get("traceability-agent", {}).get("result", {})
if trace_result:
    suspect = trace_result.get("suspect_population")
    if suspect:
        st.markdown(category_badge("Manufacturing-Data Finding"), unsafe_allow_html=True)
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Suspect Units", suspect["count"])
        sc2.metric("Bad Rate", f"{suspect['bad_rate']:.0%}")
        sc3.metric("Line / Shift", f"{suspect['line']} / {suspect['shift']}")
        sc4.metric("Component Lot", suspect["connector_lot"])
        st.markdown(f"**Common factor:** {trace_result.get('common_factor', '')}")
        st.markdown(f"**Recommended containment boundary:** {trace_result.get('recommended_containment_boundary', '')}")
        with st.expander("Segment breakdown (line x shift x component lot)"):
            st.dataframe(pd.DataFrame(trace_result.get("segment_analysis", [])), use_container_width=True)
        with st.expander("Firmware version comparison"):
            st.dataframe(pd.DataFrame(trace_result.get("firmware_analysis", [])), use_container_width=True)
        with st.expander(f"Suspect serial numbers ({suspect['count']})"):
            st.write(suspect["serial_numbers"])
    else:
        st.warning("No disproportionate production segment identified. " + trace_result.get("reasoning", ""))
else:
    st.error("Traceability agent findings unavailable.")

# --------------------------------------------------------------------------
# 7. Suspect quantity by location
# --------------------------------------------------------------------------

st.header("7. Suspect Quantity by Location")
loc = consolidated.get("suspect_quantity_by_location")
if loc:
    st.markdown(category_badge("Manufacturing-Data Finding"), unsafe_allow_html=True)
    lc1, lc2, lc3 = st.columns(3)
    lc1.metric("Tier-1 Plant (on hand)", loc["tier1_plant"]["estimated_suspect_units_on_hand"])
    lc2.metric("In-Transit", loc["in_transit"]["suspect_units"])
    lc3.metric("Delivered (OEM / Warehouse)", loc["delivered_to_oem_or_warehouse"]["suspect_units"])
    breakdown = loc["delivered_to_oem_or_warehouse"].get("breakdown_by_destination")
    if breakdown:
        st.dataframe(pd.DataFrame(breakdown), use_container_width=True)
else:
    st.info("Logistics agent was not called for this incident, or returned no location data.")

# --------------------------------------------------------------------------
# 8. Preliminary cause hypotheses (+ conflicts)
# --------------------------------------------------------------------------

st.header("8. Preliminary Cause Hypotheses")
conflicts = consolidated.get("conflicts", [])
if conflicts:
    for c in conflicts:
        st.warning(f"⚠️ **Conflict between {', '.join(c['sources'])}:** {c['description']}")

for h in consolidated.get("agent_hypotheses", []):
    st.markdown(category_badge("Agent Hypothesis"), unsafe_allow_html=True)
    st.markdown(f"*({h['source']})* {h['text']}")
    st.markdown("")

evidence_gaps = consolidated.get("evidence_gaps", [])
if evidence_gaps:
    with st.expander(f"Evidence gaps ({len(evidence_gaps)})", expanded=False):
        for g in evidence_gaps:
            st.markdown(f"- {g}")

# --------------------------------------------------------------------------
# 9. Recommended containment actions (summary)
# --------------------------------------------------------------------------

st.header("9. Recommended Containment Actions (Summary)")
for desc in consolidated.get("recommended_containment", []):
    st.markdown(f"- {desc}")

# --------------------------------------------------------------------------
# 10. Approve / Reject / Modify controls
# --------------------------------------------------------------------------

st.header("10. Approve / Reject / Modify Proposed Actions")
st.caption("No containment, notification, hold, or work-order action executes without explicit approval here.")

STATUS_ICON = {
    "awaiting_approval": "\U0001F7E1",
    "approved": "✅",
    "executed": "✅",
    "released": "🔓",
    "rejected": "❌",
    "unavailable": "⚠️",
}

for action in bundle.get("proposed_actions", []):
    with st.container(border=True):
        icon = STATUS_ICON.get(action["status"], "❓")
        header_col, badge_col = st.columns([5, 2])
        with header_col:
            st.markdown(f"{icon} **{action['action_type']}** ({action['agent']}) -- priority: {action.get('priority', 'Medium')}")
            st.markdown(action["description"])
        with badge_col:
            if action["status"] in ("approved", "executed", "released"):
                st.markdown(category_badge("Human-Approved Action"), unsafe_allow_html=True)
            else:
                st.markdown(f"status: `{action['status']}`")

        if action["status"] == "awaiting_approval":
            note_key = f"note_{action['ref_id']}"
            note = st.text_input("Modification note (optional)", key=note_key, placeholder="e.g. adjust quantity, add instructions")
            bcol1, bcol2 = st.columns(2)
            if bcol1.button("✅ Approve", key=f"approve_{action['ref_id']}"):
                api_post(
                    "/approve_action",
                    {
                        "incident_id": bundle["incident_id"],
                        "ref_id": action["ref_id"],
                        "approved": True,
                        "modification_note": note or None,
                        "approved_by": requested_by,
                    },
                )
                refresh_bundle()
                st.rerun()
            if bcol2.button("❌ Reject", key=f"reject_{action['ref_id']}"):
                api_post(
                    "/approve_action",
                    {
                        "incident_id": bundle["incident_id"],
                        "ref_id": action["ref_id"],
                        "approved": False,
                        "modification_note": note or None,
                        "approved_by": requested_by,
                    },
                )
                refresh_bundle()
                st.rerun()

# --------------------------------------------------------------------------
# 11. Initial 8D summary
# --------------------------------------------------------------------------

st.header("11. Initial 8D Summary")
draft_8d = api_get(f"/incident/{bundle['incident_id']}/8d") or bundle.get("draft_8d", {})
if draft_8d:
    st.subheader("D1 -- Team")
    st.write(draft_8d.get("D1_team", []))

    st.subheader("D2 -- Problem Description")
    d2 = draft_8d.get("D2_problem_description", {})
    st.markdown(f"**Customer:** {d2.get('customer')} | **Part:** {d2.get('part_number')} | **Urgency:** {d2.get('urgency')}")
    st.markdown(f"**Symptom:** {d2.get('symptom')}")
    with st.expander("Raw complaint text"):
        st.write(d2.get("raw_complaint"))

    st.subheader("D3 -- Proposed Interim Containment")
    for c in draft_8d.get("D3_interim_containment", []):
        st.markdown(f"- {c}")

    st.subheader("D4 -- Preliminary Causes, Conflicts & Evidence Gaps")
    d4 = draft_8d.get("D4_preliminary_causes_and_gaps", {})
    st.markdown("**Hypotheses:**")
    for h in d4.get("hypotheses", []):
        st.markdown(f"- {h}")
    if d4.get("conflicts_to_reconcile"):
        st.markdown("**Conflicts to reconcile:**")
        for c in d4["conflicts_to_reconcile"]:
            st.markdown(f"- ⚠️ {c}")
    if d4.get("evidence_gaps"):
        st.markdown("**Evidence gaps:**")
        for g in d4["evidence_gaps"]:
            st.markdown(f"- {g}")

    st.subheader("Affected Part Numbers & Suspect Quantities")
    st.write(draft_8d.get("affected_part_numbers", []))
    st.json(draft_8d.get("suspect_quantities", {}), expanded=False)

    st.subheader("Traceability Range")
    st.json(draft_8d.get("traceability_range", {}), expanded=False)

    st.subheader("Customer Communication Summary")
    st.markdown(draft_8d.get("customer_communication_summary", ""))

    st.subheader("Approved Actions & Owners")
    approved = draft_8d.get("approved_actions", [])
    if approved:
        st.dataframe(pd.DataFrame(approved), use_container_width=True)
    else:
        st.caption("No actions approved yet.")

# --------------------------------------------------------------------------
# 12. Audit / message history table
# --------------------------------------------------------------------------

st.header("12. Audit / Message History")
audit_events = api_get(f"/audit/{bundle['correlation_id']}") or []
if audit_events:
    df = pd.DataFrame(audit_events)
    df = df.sort_values("id")
    display_cols = ["timestamp", "correlation_id", "sender", "recipient", "action", "event_type", "status"]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, height=350)
else:
    st.caption("No audit events yet.")

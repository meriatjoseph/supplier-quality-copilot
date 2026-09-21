# Sample Run: Initial 8D Output

This is a saved example of the system's auto-generated initial 8D draft
from one full run of the Supplier Quality Copilot, included as a
deliverable per the take-home spec. This run used a real OpenAI LLM
(`LLM_PROVIDER=openai`) for incident extraction, RAG interpretation, and
embeddings, and exercises all 7 approval states in this system (executed,
rejected, awaiting_approval, and released — see "Approved Actions & Owners"
below). The raw JSON for this run (full incident bundle, 8D, and audit
trail) is alongside this file in `sample_run/`.

- **Incident ID:** `OEM-INC-1B0A7BD7`
- **Correlation ID:** `CORR-EC51B125`
- **Complaint submitted:** "Northbridge Motors urgent: intermittent
  steering warning lamp EPS-2200-A, 2025-05-08 to 2025-05-18, some units
  shipped."

---

## D1 — Team

- quality-rag-agent (automated agent)
- traceability-agent (automated agent)
- process-maintenance-agent (automated agent)
- logistics-agent (automated agent)
- Human Quality Manager (approval authority)

## D2 — Problem Description

| Field | Value |
|---|---|
| Customer | Northbridge Motors |
| Part Number | EPS-2200-A |
| Urgency | High |
| Symptom | Intermittent steering warning lamp |

## D3 — Proposed Interim Containment

1. Recalibrate and inspect PRESS-4B connector press force cell/tooling. 21 of 25 units in the investigation window read outside the 45.0–65.0N control-plan spec.
2. Place inventory hold on 6 suspect unit(s) of EPS-2200-A at Tier-1 Plant. Hold all units from Line 2, Evening shift, component lot CON-771, produced 2025-05-09 14:28 to 2025-05-16 21:48 (19 units).
3. Issue shipment-block / intercept instruction for 2 suspect unit(s) currently in-transit to Northbridge. (Same boundary as above.)
4. Request 100% sort/inspection and OEM notification for 11 suspect unit(s) already delivered to Northbridge/third-party warehouse. Do not contact dealers directly per containment procedure — escalate through Northbridge Supplier Quality.

## D4 — Preliminary Cause Hypotheses & Evidence Gaps

**Hypotheses (tagged by originating agent):**

- *(quality-rag-agent, Agent Hypothesis — real LLM-generated, GPT via OpenAI)* "The retrieved passages indicate that the intermittent steering warning lamp issue with the EPS-2200-A is likely related to the connector insertion force, as under-force insertion can lead to intermittent electrical connections that may not be detected during end-of-line testing. Given that EPS control modules are classified as safety-critical components, the team must adhere to a zero-defect expectation and maintain a low field PPM for safety-related complaints. The historical 8D report highlights a similar symptom without a stored diagnostic trouble code, suggesting that the issue may not be linked to a specific sensor fault. The team should verify the connector insertion force during assembly and review any recent firmware changes that could affect the steering warning lamp logic, ensuring compliance with configuration control requirements."
- *(traceability-agent, Agent Hypothesis)* Segment **Line 2 / Evening shift / Connector Lot CON-771** is the narrowest grouping (line × shift × component lot) showing a disproportionate EOL Marginal/Fail concentration — **95% vs 30% baseline** — and meets the minimum group size (5 units) to be a meaningful pattern rather than noise. Firmware version shows a notable bad-rate spread (14%) and should also be considered as a contributing factor.
- *(process-maintenance-agent, Agent Hypothesis)* Machine **PRESS-4B**: 21/25 units (84%) had connector insertion force outside the 45.0–65.0N control-plan limit, with 21 FORCE_LOW alarms logged on this machine in-window. Maintenance records show a force-cell calibration and worn-tooling issue on PRESS-4B, corrected 2025-05-16.

**Conflicts to reconcile:** None surfaced in this run (the RAG query's
top-k results didn't include the historical firmware-8D passage strongly
enough to trigger the conflict heuristic in this instance — though notice
the LLM's own interpretation above independently referenced "the historical
8D report" and correctly reasoned that current evidence points to a
connector/hardware cause rather than assuming a repeat of that precedent).
The conflict-detection heuristic (`coordinator-agent/consolidation.py::detect_conflicts`)
is verified working via a direct test when both signals are present.

**Evidence gaps:** None in this run — all 4 selected agents returned usable results, RAG found supporting evidence, and Traceability identified a disproportionate segment.

## Affected Part Numbers & Suspect Quantities

- **Affected part numbers:** EPS-2200-A
- **Total suspect units:** 19
  - Tier-1 Plant (on hand): 6
  - In-Transit: 2
  - Delivered (OEM / Third-Party Warehouse): 11
    - Northbridge Assembly Plant – Danforth: 1 (Delivered)
    - Northbridge Assembly Plant – Riverbend: 3 (Delivered) + 2 (In-Transit)
    - Third-Party Warehouse – Midwest DC: 7 (Delivered)

## Traceability Range

- **Date range analyzed:** 2025-05-08 to 2025-05-18
- **Containment boundary:** Hold all units from Line 2, Evening shift, component lot CON-771, produced 2025-05-09 14:28 to 2025-05-16 21:48 (19 units).

## Customer Communication Summary

> Draft notification to Northbridge Motors Supplier Quality: suspect
> population of 19 units identified (Line 2, Evening shift, component lot
> CON-771, produced 2025-05-09 14:28 to 2025-05-16 21:48); interim
> containment actions proposed and pending/receiving approval; root cause
> investigation ongoing per D4.

## D5/D6/D7 Status

Not yet started — pending root cause confirmation and effectiveness
verification (permanent corrective action and effectiveness verification
are out of scope for this initial draft, per the take-home's scope).

## Approved Actions & Owners

| Action Type | Owner Agent | Status | Description |
|---|---|---|---|
| work_order | process-maintenance-agent | executed | Recalibrate and inspect PRESS-4B connector press force cell/tooling. |
| inventory_hold | logistics-agent | executed | Place inventory hold on 6 suspect units at Tier-1 Plant. |
| shipment_block | logistics-agent | **rejected** *(human judged the 2 in-transit units low-risk enough to intercept at destination instead)* | Issue shipment-block for 2 in-transit units. |
| 100_percent_sort | logistics-agent | **awaiting_approval** *(left pending in this run, to demonstrate a mixed-state action list)* | Request 100% sort/inspection for 11 delivered units. |
| oem_notification | coordinator-agent | executed | Notify Northbridge Motors Supplier Quality per CSR Section 5. |
| 8d_update | coordinator-agent | executed | Submit interim 8D (D1–D3) to Northbridge Motors Supplier Quality. |
| **release_material** | logistics-agent | **released** *(demonstrates "Release previously contained material" — proposed automatically only after the inventory_hold above actually reached `executed`, and itself required a separate human approval)* | Release previously-contained material for approved inventory_hold (ref `ACT-BEEFD577`) back to shippable status, once root cause is confirmed resolved. |

---

*Every step above (dispatch, response, health check, approval, execution,
and the release) is recorded in the audit log keyed by
`correlation_id=CORR-EC51B125` (44 events in this run) — see
`sample_audit_log.json` alongside this file.*

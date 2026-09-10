# Demo Script

A step-by-step walkthrough for a live demo: submit complaint → agents
respond → review findings → approve action → view 8D.

## 0. Start the system

```bash
docker compose up --build
```

Wait for all health checks to pass (Coordinator's `depends_on ... condition:
service_healthy` will block startup order automatically). Open
**http://localhost:8501**.

## 1. Submit a complaint

In the "1. Submit OEM Complaint" box, use (or replace with) the pre-filled
example:

> Northbridge Motors is reporting intermittent steering warning lamp
> illumination on EPS-2200-A modules, urgent safety concern. Vehicles built
> between 2025-05-08 and 2025-05-18. Several units have already shipped to
> the assembly plant.

Click **Submit Complaint**. Point out while it's loading: this single call
triggers LLM extraction, dynamic agent selection, and a two-phase REST
dispatch to up to 4 agents — all before returning.

## 2. Extracted incident details

Section 2 shows the structured extraction: customer, part number, symptom,
date range, urgency, and the generated `incident_id`/`correlation_id`. Note
this happened via one LLM call (or the rule-based fallback if no LLM key is
configured — the system works either way).

## 3–4. Routing decision + agent health

Section 3 shows *which* agents were selected and *why* (the heuristic
reasoning string per agent) — point out that RAG and Traceability always
run, while Process/Maintenance and Logistics were selected here because of
the `urgency=high` + symptom-keyword heuristics in `select_agents()`.

Section 4 shows live up/down status and response time per agent, from a
`/health` ping made before/alongside dispatch.

**Resilience demo (optional):** in another terminal, run
`docker compose stop logistics-agent`, then submit a new complaint. Show
that the workflow still completes — Logistics shows red/unavailable, and
an evidence gap is listed — nothing crashes or hangs. Restart with
`docker compose start logistics-agent`.

## 5. Retrieved source passages

Section 5 shows RAG's retrieved evidence, each tagged **📘 Retrieved
Requirement** with document name + section citation — point out this is
kept separate from the RAG agent's own interpretation, shown just below
tagged **🧩 Agent Hypothesis**.

## 6–7. Traceability + suspect quantities

Section 6 shows the reasoned suspect population: a specific line/shift/
component-lot segment with its EOL Marginal/Fail rate stated against the
overall baseline (e.g. "95% vs 30% baseline, 3.2x higher") — not a raw data
dump. Expand "Segment breakdown" to show the full grouped table.

Section 7 shows the same suspect population's quantities broken out by
location (Tier-1 plant / in-transit / delivered), computed by the
Logistics agent from the exact suspect serial numbers Traceability
identified — point out this is the "Phase 2 scoped by Phase 1" part of the
orchestration (see `ARCHITECTURE.md`).

## 8. Preliminary cause hypotheses (+ conflicts)

Section 8 shows each agent's hypothesis tagged **🧩 Agent Hypothesis**. If
a complaint's RAG query happens to retrieve the historical firmware-related
8D report alongside a connector-force-driven traceability finding, a
**⚠️ Conflict** banner appears here explaining the disagreement explicitly
rather than silently picking one cause — this is one of the acceptance-bar
requirements, worth calling out if it appears.

## 9–10. Containment actions + approval

Section 9 lists proposed containment actions as a summary. Section 10 is
where the human-in-the-loop control lives: each proposed action
(inventory hold, shipment block, 100% sort, work order, OEM notification,
8D update) has its own **✅ Approve** / **❌ Reject** buttons and an
optional modification-note field.

- Click **Approve** on the work order — show it flip to executed and get
  tagged **✅ Human-Approved Action**.
- Click **Reject** on the shipment-block action — show it flip to
  `rejected` without executing.
- Try the modification-note field on the inventory-hold action before
  approving, to show the "Modify" pathway.
- After approving the inventory-hold action, a new **🔓 release_material**
  action appears automatically in the list — this is the "Release
  previously contained material" approval case. Approve it to show the
  hold flip from executed to released; note it's only offered once a hold
  has actually been executed (you can't release material that was never
  held).

Emphasize: nothing in this system reaches `executed`/`released` status without this
explicit step, for every action type.

## 11. Initial 8D summary

Section 11 shows the auto-generated 8D draft, assembled entirely from data
already collected in this run (no new analysis) — D1 team, D2 problem
description, D3 interim containment, D4 causes/conflicts/evidence gaps,
affected part numbers and suspect quantities, traceability range, customer
communication summary, and the live-updating "Approved Actions & Owners"
table (reflecting the approvals just made in Section 10). Compare against
the saved example in `sample_run/sample_8d_output.md`.

## 12. Audit trail

Section 12 shows the full audit/message history for this incident's
`correlation_id` — every dispatch, response, health check, approval
decision, and execution, in order, with sender→recipient and status. This
is the end-to-end traceability requirement: point to a specific row (e.g.
the `approval_decision` event) and show its `correlation_id` matches every
other row for this incident.

## Wrap-up talking points

- Five independent FastAPI processes + one Streamlit frontend, communicating
  only over REST/JSON with a shared Pydantic contract — no orchestration
  framework.
- Dynamic agent selection, not a fixed pipeline.
- Mandatory human approval before any operational action, per-action (not
  one global "approve everything" button).
- Graceful degradation when an agent is down.
- Full correlation-ID traceability via the audit log.

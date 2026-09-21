# Supplier Quality Copilot

**Repository:** https://github.com/meriatjoseph/supplier-quality-copilot
**Stack:** Python 3.11 · FastAPI/uvicorn · Pydantic v2 · httpx · LangChain (core/community/text-splitters) · FAISS · pandas · SQLite · Streamlit · Docker Compose · LLM swappable via env (Google Gemini default, OpenAI, Anthropic, or none)
**Status:** Working prototype. The full workflow runs end to end with no API key, and was re-verified locally on 2026-09-21. It has no automated tests and no CI.
**Timeline:** 2 commits, both 2026-09-10. File timestamps put the build at roughly 2026-09-09 19:49 → 22:32 (soft, since OneDrive can alter them), then docs on 2026-09-10 · audit and two fixes 2026-09-21 (uncommitted, see §17)
**Head:** `4b02e61` on `main`. Working tree has 2 modified files from the 2026-09-21 fixes.
**Size:** 56 tracked files (+ this report), ~3,460 lines of Python (~3,120 excluding the data generator), 5 services + 1 UI

**Verification scope (2026-09-21).** All five services were run locally in a throwaway venv outside the repo, with no LLM key (so the offline embedder and rule-based extraction were used). The RAG eval was re-run. Not exercised: Docker Compose, the Streamlit UI, and any LLM-backed path (Gemini/OpenAI/Anthropic). `.env` was not opened; it is gitignored and untracked.

---

## 1. Overview & Business Problem

When an OEM reports that intermittent steering-warning lamps are coming from a Tier-1 supplier's electronic power-steering (EPS) module, the supplier has hours, not days, to answer four questions:
- Which requirements apply?
- Which production units are suspect?
- What is the likely process cause?
- What can be contained, and where is it now (plant, in transit, delivered)?

Today that means a quality manager pulling from documents, an MES, a maintenance log and a logistics system by hand.

The Supplier Quality Copilot compresses that first investigation into one submission. A Coordinator agent extracts the incident, dispatches specialist agents over REST, consolidates their findings, and surfaces conflicts. It then holds every operational action for explicit human approval. It also drafts an initial 8D report and records every step in an audit log keyed by `correlation_id`.

All data is synthetic: one fictional OEM ("Northbridge Motors") and one part family (EPS-2200). This is a scoped exercise against a written brief (the "Two-Day Build Challenge" `.docx` in the repo), not a production system.

## 2. Use Case & Objectives

**Primary use case:** a quality manager pastes an OEM complaint and gets a routed, cited, human-gated investigation.

Objectives, taken from the brief's 13 acceptance criteria, with status as verified:
- **Distributed agents:** at least two independent services communicating over documented APIs. Done: 5 FastAPI services plus a Streamlit UI.
- **RAG with citations:** document and section references, and a refusal when the evidence is missing. Done, with caveats (§12–13).
- **Reasoned suspect population:** a segment with the ratio stated, not a raw dump. Done.
- **Human approval before any operational action.** Done, including server-side enforcement of the approval state machine as of the 2026-09-21 fix (§13 F1, §17).
- **Graceful degradation when an agent is down.** Done, verified.
- **Correlation-ID audit trail and an initial 8D draft.** Done.
- **Runs from the README.** The local path works. The Docker path was not run in this audit.

## 3. Proposed Solution

Five FastAPI processes and one Streamlit UI, talking only over REST/JSON with one shared Pydantic envelope (`AgentMessage` / `AgentResponse`). There is no orchestration framework; the coordinator is hand-written Python.

Dispatch is two-phase:
1. RAG and Traceability always run.
2. Process/Maintenance and Logistics are then selected by heuristic and scoped by Traceability's suspect population (line, shift, lot, serial numbers).

Findings are consolidated into four labelled categories: Retrieved Requirement, Manufacturing-Data Finding, Agent Hypothesis, and Human-Approved Action.

## 4. Project Architecture

Still a set of small services around one orchestrator. The service split is real: separate processes, ports and Dockerfiles.

| Layer | Module | Responsibility |
|---|---|---|
| UI | `frontend/app.py` (Streamlit :8501) | 12-section walkthrough, category badges, per-action approve/reject/modify, audit table |
| Orchestration | `coordinator-agent/` (:8000) | `extraction.py` (LLM + regex fallback), `orchestration.py` (agent selection, two-phase dispatch), `consolidation.py` (4 categories, conflicts, gaps, actions), `eightd.py` (draft 8D), `app.py` (incident store, `/approve_action`) |
| Retrieval | `quality-rag-agent/` (:8001) | Header-aware chunking, FAISS, relevance floor, evidence and interpretation in separate fields |
| Traceability | `traceability-agent/` (:8002) | Segments production by line × shift × connector lot and firmware; flags disproportionate bad-rate |
| Process | `process-maintenance-agent/` (:8003) | Connector force vs the 45–65 N limit, alarms/calibration/maintenance cross-reference, proposed work order |
| Logistics | `logistics-agent/` (:8004) | Suspect quantity at plant / in transit / delivered, proposed hold / block / 100%-sort / release commands |
| Shared | `shared/` | Message schema, static-key auth, `dispatch()` with timeout/retry, task dedup, SQLite audit log, LLM/embeddings factory with offline fallback |
| Data | `data/docs/` (6 docs), `data/manufacturing/` | Synthetic controlled documents; generator, CSVs and a SQLite DB |
| Eval | `rag_eval/eval_rag.py` | 7 retrieval cases |
| Deploy | `docker-compose.yml` | 6 services, healthchecks, `depends_on: service_healthy`, shared audit volume |

Incident state lives in coordinator memory (`INCIDENTS: dict`). The audit log is the only thing that survives a restart.

## 5. Folder Structure

```
supplier quality copilot/
├── coordinator-agent/        app.py extraction.py orchestration.py consolidation.py eightd.py
├── quality-rag-agent/        app.py ingest.py
├── traceability-agent/       app.py
├── process-maintenance-agent/ app.py
├── logistics-agent/          app.py
├── frontend/                 app.py   (Streamlit)
├── shared/                   schema.py auth.py http_client.py dedup.py audit.py llm.py
├── data/
│   ├── docs/                 6 controlled documents (~2,600 words total)
│   └── manufacturing/        generate_data.py, 6 CSVs, manufacturing.db (76 KB)
├── rag_eval/eval_rag.py
├── sample_run/               8D (md+json), incident bundle, audit log
├── docker-compose.yml        one Dockerfile + requirements.txt per service
├── README.md  ARCHITECTURE.md  MESSAGE_CONTRACT.md  DEMO.md  PROJECT_REPORT.md
└── Automotive Tier-1 ... Two-Day Build Challenge.docx   (the brief)
```

Two structural notes:
- There is no `tests/`, CI workflow, lint config or lockfile.
- The index isn't persisted. The RAG agent rebuilds its FAISS index (46 chunks) at every startup.

## 6. End-to-End Workflow

1. **Submit.** The UI posts free text to `/submit_complaint` with a `request_id`, which is an idempotency key. A repeat with the same key returns the same incident (verified).
2. **Extract.** An LLM returns JSON: customer, part number, symptom, date range, urgency. Any failure, or no key, falls back to regex rules. It never hard-fails.
3. **Route.** `select_agents()` always includes RAG and Traceability. It adds Process/Maintenance and Logistics on high/critical urgency or keyword matches. In practice most complaints select all four.
4. **Health check and Phase 1.** Each selected agent is pinged, then RAG and Traceability are dispatched.
5. **Phase 2, scoped by Phase 1.** Process/Maintenance gets the suspect line, shift and lot. Logistics gets the suspect serials.
6. **Consolidate.** The coordinator builds the four categories, conflicts, evidence gaps and proposed actions, then the 8D draft.
7. **Approve.** Each action has its own approve/reject/modify control. Only actions that are `awaiting_approval` (or retryable `unavailable`) accept a decision; anything else returns HTTP 409. Approval dispatches an `execute_*` message to the owning agent.
8. **Follow-on.** Once a hold is executed, a `release_material` action is proposed automatically, and it needs its own approval.
9. **Audit.** Every dispatch, response, approval and execution is written to the shared SQLite log by whichever service performed it.

## 7. Technologies Used

| Category | Technology | Role |
|---|---|---|
| Services | FastAPI + uvicorn, Pydantic v2 | 5 REST services, shared message contract |
| Inter-service | httpx | `dispatch()` with 5 s timeout, 2 attempts; `/health` pings |
| RAG | LangChain text-splitters, FAISS (flat L2) | Header-aware chunking, retrieval |
| LLM | Gemini (`gemini-2.0-flash` default), OpenAI (`gpt-4o-mini`), Anthropic (`claude-sonnet-5`) | Extraction and RAG interpretation, via `LLM_PROVIDER`. Anthropic has no embeddings, so those fall back |
| Embeddings | Google `text-embedding-004` / OpenAI `text-embedding-3-small` / offline hashed bag-of-words (384-dim) | The offline embedder means no key is needed |
| Data | SQLite + pandas | Production, alarms, calibration, maintenance, inventory, shipments |
| Audit | SQLite (WAL) on a shared Docker volume | Append-only, keyed by `correlation_id` |
| UI | Streamlit | Approval and review surface |
| Deploy | Docker Compose, `python:3.11-slim` | One-command bring-up |
| Auth | Static `X-API-Key` | Simplified service-to-service stand-in |
| Testing | `rag_eval/eval_rag.py` only | 7 retrieval cases |

## 8. Implementation Details

**Chunking.** Markdown `#`/`##` headers are split first, so each chunk carries `document` and `section` metadata. Each section is then split again at 800 characters with 120 overlap. Result: 6 documents → 46 chunks (rebuilt and counted 2026-09-21).

**Retrieval.**
- It pulls a candidate pool of 15 and computes relevance as `1/(1+L2)`.
- It drops anything under a floor: 0.45 for real embeddings, 0.40 for the offline embedder, chosen at startup by whichever embedder actually initialised.
- The coordinator requests 5 results; the service default is 4.
- `evidence` and `interpretation` are always separate fields. When nothing clears the floor, the agent returns `no_evidence_found: true` and a "do not assume a requirement exists" message instead of an answer.

**Traceability.**
- It filters by date and part number, then groups by line × shift × connector lot with a minimum group size of 5.
- A segment is flagged only if its bad-rate is at least 2× the overall rate and at least 25% absolute.
- It reports the ratio and counts as the reasoning, and separately compares firmware versions to test the alternate hypothesis.

**Process/Maintenance.**
- It hard-codes the control-plan limits (45–65 N, checked against the doc) and finds machines with out-of-spec readings.
- For each such machine it joins FORCE alarms, calibration gap (>30 days) and maintenance records within ±10 days.
- It proposes a work order, held pending approval.

**Logistics.**
- It matches suspect serials to shipments and splits them into plant, in-transit and delivered.
- It emits `inventory_hold`, `shipment_block` and `100_percent_sort` commands that stay `awaiting_approval`.
- `release_containment_action` only works on a command that is already `executed`.

**Resilience.**
- `dispatch()` never raises. It returns a synthetic `AgentResponse` with status `unavailable`, `timeout` or `error`.
- Each agent caches responses by `task_id`, so a retried `execute_*` message is not re-run.

**Approval gate.** `/approve_action` looks up the action, rejects the call with 409 unless its status is in `APPROVABLE_STATUSES = {awaiting_approval, unavailable}`, applies any modification note, logs the decision, and dispatches to the owning agent (or flips coordinator-native actions directly). `unavailable` stays retryable because the downstream agent never confirmed execution.

**Consolidation notes.**
- The "24-hour OEM notification" and "3-day interim 8D" wording in the proposed actions is hard-coded in the coordinator. It matches CSR §4–5, but it is a constant, not something the RAG agent retrieved.
- Conflict detection is a bespoke check for one scenario: a historical firmware 8D against the current firmware spread.

**Data.** 260 production units (2025-04-20 → 05-20), 143 shipments (117 delivered, 26 in transit), 29 alarms, 13 calibration records, 5 maintenance records and 8 inventory rows. A fault is injected deliberately: Line 2 / Evening / lot CON-771, with PRESS-4B force drifting low after a missed calibration.

## 9. Methodology

A single build sprint against a written brief: specification first, then the synthetic data, then the agents, then the UI and docs.

- Two commits, no branches or PRs, and no tests.
- The `sample_run/` artefacts were captured from a live run.
- The README's "Key assumptions", "Known limitations" and "Explicitly out of scope" sections state the scope trade-offs.

| Date | Milestone |
|---|---|
| 2026-09-09 (approx., from file timestamps) | Brief saved 19:49; compose, agents, RAG, data generator, coordinator and frontend written; docs and sample run by 22:32 |
| 2026-09-10 | `6a6d593` initial commit; `4b02e61` documents manual verification of agent-unavailability handling |
| 2026-09-21 | Independent audit: services run, eval re-run, edge cases probed (§13); F1 and F2 fixed and re-verified (§17) |

## 10. Results

Measured 2026-09-21 by running all five services locally, with no LLM key, so the offline embedder and rule-based extraction were used. Figures in this section were taken before the F1 fix and are unaffected by it, except where noted.

- **Boot.** All five services report healthy. The RAG agent indexes 46 chunks; Traceability loads 260 records.
- **Demo complaint.** `/submit_complaint` returns 200 in about 1.5 s, with each agent replying in roughly 155–175 ms.
- **Routing.** All four agents were selected, since urgency was high.
- **Suspect population.** 19 units on Line 2 / Evening / CON-771, with 18/19 (95%) Marginal/Fail against a 30% window baseline, 3.2× higher. That matches the saved sample run.
- **Firmware.** 3.8.0 at 20.8% and 3.8.1 at 34.9% bad-rate, a 14% spread.
- **Suspect quantities.** 6 at the plant, 2 in transit, 11 delivered.
- **Process finding.** PRESS-4B had 21/25 units (84%) outside 45–65 N.
- **Actions.** 6 proposed, all `awaiting_approval`. There were **0 execution events in the audit log before any approval** (19 events by then).
- **Approval loop.** Approving the hold executed it and auto-proposed `release_material`. Approving that moved it to `released`. One full incident lifecycle produced 52 audit events (44 in the saved sample) in the pre-fix run, which included the duplicate approvals F1 allowed.
- **Security basics.** No API key → 401. A repeated `request_id` → the same incident.
- **Degradation.**

| Agents down | HTTP | Time | What the coordinator did |
|---|---|---|---|
| Logistics | 200 | 7.7 s | `agent_health.up=false`, `status: "unavailable"`, one evidence gap, no location data, 3 proposed actions instead of 6 |
| Logistics + Traceability | 200 | 13.8 s | Both marked unavailable, 2 evidence gaps, consolidated result and 8D still returned |

## 11. Evaluation Metrics

| Metric | Where | Current value |
|---|---|---|
| Retrieval top-1 document/section hit | `rag_eval/eval_rag.py` | **6/6** positive cases (re-run 2026-09-21, offline embedder) |
| Abstention (`no_evidence_found`) | same | 1/1 in the suite; 5/6 in my wider probe (miss in §13, F4) |
| Relevance margin (offline embedder) | measured | Top-1 scores 0.417–0.462 against a floor of 0.40 |
| Suspect-segment recovery | Traceability | Finds the injected segment: in-window 18/19 (95%) vs 30%; full dataset 24/32 (75%) vs 16.5% |
| Process deviation | Process agent | PRESS-4B 22/140 out of spec vs PRESS-4A 1/120 (whole dataset) |
| Approval gating | Audit log + API | 0 execution events before approval; after the F1 fix, 409 on any decision for a non-pending action |
| Per-agent latency | `duration_ms` in the envelope | ~155–175 ms locally without LLM; RAG 3,790 ms with a real LLM (sample run) |
| Automated tests / CI | none | None |
| Faithfulness of the LLM interpretation | not measured | None |

## 12. Result Analysis

The end-to-end workflow works and is coherent. Every claim in the saved sample's headline (95% vs 30%, 19 units, 6/2/11 split, 21/25 out of spec) reproduces from the shipped database.

Three things the numbers don't prove:
- **The traceability result is circular.** The generator injects the fault and the heuristic is built to find it. It shows the pipeline works. It does not show the method would find an unplanted cause.
- **The RAG eval is small and lenient.**
  - Seven cases were used to tune the two relevance floors, so it is a tuning set, not a held-out test.
  - It accepts any section of the expected document. Case 3 ("root cause of the 2023 complaint") passes with the top hit at "D2: Problem Description", not "D4: Root Cause".
  - Case 5 passes on PFMEA "Section 5: Recommended Priority".
- **Retrieval scores are thin.** With the offline embedder, all the true positives sit between 0.417 and 0.462, and the floor is 0.40.

The generator writes a "30-day calibration cycle" story, but PRESS-4B's records show a passing calibration on 05-07, only 11 days before the window ends. So the `calibration_gap` check never fires. The README discloses this. The alarms, the `Fail - Recalibrated` record and the maintenance entry carry the story instead.

## 13. Auditing & Validation of Outcomes

**Verified working**
- Approval gate: no execution happens before an approval. The audit log shows 0 execution events beforehand.
- Server-side state machine (after the F1 fix): approve-after-reject and re-approval both return 409; the `unavailable` retry path is not blocked.
- Two-phase scoping, `task_id` dedup, `request_id` idempotency, and 401 on a missing key.
- Graceful degradation of 1 and 2 agents (§10).
- Evidence and interpretation stay in separate fields, and the UI labels the four categories.
- `.env` is gitignored and not tracked.
- Requirement wording hard-coded in the actions (24 h notify, 3-day interim 8D) matches CSR §4–5.

**Findings from this audit (2026-09-21)**

- **F1: Approval state machine wasn't enforced server-side. FIXED (§17).**
  - Before: `/approve_action` never checked that the action was still `awaiting_approval`.
  - Rejecting `shipment_block` and then approving it returned `executed`.
  - Re-approving an executed hold succeeded and added a duplicate `human_approved_actions` entry (6 entries for 5 distinct actions).
  - The UI only shows buttons on pending actions, so this was reachable through the API only.
  - Still open: `approved_by` is a self-declared string, not an authenticated identity.
- **F2: The sample 8D markdown contradicted its own JSON. FIXED (§17).**
  - The `.md` said firmware is "not considered a differentiating factor" at a 14% spread.
  - The saved JSON and the code both say it is a "notable bad-rate spread… should also be considered as a contributing factor".
  - Still open: the sample was produced with OpenAI, while the repo's default provider is now Google. There is no recorded run for the Gemini path.
- **F3: The conflict detector can't be shown end to end. Open. (Verified.)**
  - It fires when called directly with synthetic input.
  - In 6 complaint variants (offline embedder) it never fired.
  - In the demo window it can't: it needs a firmware spread under 10%, and the demo window's spread is 14.1%.
  - Even when the 8D document was retrieved (2 of 6 variants), the retrieved chunk didn't contain the word "firmware".
  - DEMO.md and the README already call it conditional and a targeted heuristic. Real embeddings may retrieve differently.
- **F4: The abstention guard let through one off-topic query. Open. (Verified.)** "How do I reset the steering wheel angle sensor on a Ford F-150?" returned evidence at 0.411 with `confidence: "medium"`. The other 5 probes declined correctly. The floor separates on lexical overlap, not meaning.
- **F5: The `"medium"` confidence label is unreachable with real embeddings. Open. (Read from code.)** The floor (0.45) equals the "high" threshold, so any retrieved result is "high".
- **F6: Serial dispatch penalty is additive. Open. (Measured locally; the Docker figure is inferred.)**
  - Each dead agent added about 6 s on this Windows machine.
  - The README documents about 18 s per stopped agent under Docker, and the frontend's timeout is 30 s.
  - So two dead agents under Docker would probably time out the UI while the coordinator finishes anyway. Not tested.
  - Phase 1's RAG and Traceability calls are independent but run one after the other.
- **F7: Small consistency issues. Open.**
  - `ingest.py`'s docstring says "cosine-similarity-style" but FAISS is using flat L2.
  - `AgentMessage.max_attempts` defaults to 3 while the client makes 2 attempts.
  - `langchain-community` prints a sunset deprecation warning on import.
  - All requirements are `>=` with no lockfile.
  - `shared/audit.py` opens the DB at import time.

**Open, and honestly labelled as such**
- The Streamlit UI and the Docker Compose path were not exercised in this audit.
- No LLM-backed behaviour was verified: extraction quality, interpretation faithfulness, and the Gemini/OpenAI/Anthropic swap.
- Incident state is lost on coordinator restart (disclosed in the README).
- The shared static key and the default secret `dev-shared-secret-change-me` are development stand-ins.

## 14. Challenges Faced

- **No real data.** The synthetic dataset had to tell one consistent root-cause story across the CSVs, the DB, the maintenance log and the six controlled documents.
- **Running with no API key.** Extraction, interpretation and embeddings each need an offline path, so the system boots with nothing configured.
- **Score scales differ by embedder.** Real and offline embeddings produce relevance on different scales. That led to two empirically tuned floors selected at startup.
- **Safe retries.** A retried timeout must not re-run a non-idempotent `execute_work_order`, which is why every agent dedups on `task_id`.
- **One audit trail across containers.** Every service writes to a shared SQLite file (WAL mode) on a Docker volume rather than routing through the coordinator, so the trail survives a coordinator restart.
- **Keeping a human in the loop without a comms agent.** `oem_notification` and `8d_update` are coordinator-native pseudo-actions that still go through approval.

## 15. Limitations

- Synthetic data only: one OEM, one part family, one injected fault. The heuristics were built against that fault.
- Retrieval is small-scale and tuned on its own test set (46 chunks, 7 cases, a floor 0.017 below the lowest true positive).
- Agent selection is keyword heuristics; nearly every complaint selects all four agents.
- Conflict detection covers one scenario only.
- Dispatch is sequential, so latency grows with every agent and dead agents cost seconds each.
- Incident state is in memory; there is no persistence or multi-user isolation.
- Auth is a single shared key; `approved_by` is not an identity.
- No tests, CI, lint, pinned dependencies, or structured logging or metrics.
- No VIN → build-date back-calculation; the date range maps straight to production timestamps.
- The LLM interpretation is neither grounded nor scored.

## 16. Future Improvements

**Immediate**
1. ~~Enforce the approval state machine server-side.~~ Done 2026-09-21 (§17).
2. ~~Fix `sample_8d_output.md` to match its JSON.~~ Done 2026-09-21 (§17). Still to do: re-record a sample run on the default (Gemini) provider.
3. Add a `tests/` suite (schema, dedup, `dispatch()` failure modes, consolidation, approval transitions including the new 409 behaviour), then wire it into CI. It can run offline.
4. Pin dependencies.

**Next**
5. Dispatch RAG and Traceability concurrently, and Process and Logistics concurrently in Phase 2.
6. Replace the relevance floor with a held-out eval set, including near-domain negatives like the F4 probe. Fix the confidence bands.
7. Persist incidents in SQLite or Postgres.
8. Add real authentication and an approver identity.

**Standing items**
9. Give the conflict detector an end-to-end fixture, or generalise it.
10. Measure LLM interpretation faithfulness.
11. Vary the fault in the generator so the traceability method is tested on cases it wasn't built for.

## 17. Change Log: What Was Done on 2026-09-21 (Before → After)

Two fixes, both found by the audit in §13 and both re-verified by running the services. **Not committed:** `git status` shows 2 modified files. This report is the only new file.

### Change 1: Enforce the approval state machine (F1)

**File:** `coordinator-agent/app.py` (+13 lines)

| | Before | After |
|---|---|---|
| Check in `/approve_action` | None. Any action could receive a decision in any state | Returns **HTTP 409** unless the action's status is in `APPROVABLE_STATUSES = {"awaiting_approval", "unavailable"}` |
| Approve after reject | `shipment_block` rejected, then approved → **`executed`** | 409: "already 'rejected'" |
| Approve twice | Hold re-approved → 200 `executed`, duplicate entry in `human_approved_actions` | 409: "already 'executed'" |
| Release twice | Not blocked | 409: "already 'released'" |
| `human_approved_actions` after a full approval run | 6 entries for 5 distinct actions | 4 entries for 4 distinct actions |
| Agent down at approval time | Action set to `unavailable` | Unchanged. Retry is still allowed (two attempts both returned 200 `unavailable`, not 409) |
| Normal flow (hold → auto-proposed release → release; reject; coordinator-native actions) | Worked | Unchanged. Verified end to end |

**Design choice:** `unavailable` stays approvable because the downstream agent never confirmed execution, so a retry is the correct recovery. The 409 is raised before the modification note is applied and before anything is logged or dispatched, so a refused call leaves no trace on the action.

**Still open from F1:** `approved_by` is a self-declared string, so the gate enforces state, not identity.

### Change 2: Correct the sample 8D wording (F2)

**File:** `sample_run/sample_8d_output.md` (1 line changed)

| | Text |
|---|---|
| **Before** | "Firmware version shows only a 14% bad-rate spread and is not considered a differentiating factor in this window." |
| **After** | "Firmware version shows a notable bad-rate spread (14%) and should also be considered as a contributing factor." |

**Why:** the traceability agent only says "not a differentiating factor" when the spread is under 10%. At 14% it says "notable… contributing factor". That is what the saved JSON bundle and the live code output, and I confirmed it against a fresh run. The markdown had the opposite conclusion. A grep found no other file with the wrong wording. (`traceability-agent/app.py` and `consolidation.py` contain the phrase only inside the correct <10% branch.)

### Verification performed after the changes

- Five services relaunched locally; a full complaint → approve/reject/release sequence was run against the fixed coordinator (results in the table above).
- The `unavailable` retry path was tested by killing the logistics agent, then approving the same hold twice.
- No other behaviour was re-measured; the §10 figures were taken before the fix and the fix does not touch those paths.

### Not changed

F3–F7 remain open exactly as described in §13. No tests were added, no documentation other than the sample 8D was updated, and `MESSAGE_CONTRACT.md` does not yet document `/approve_action` or its 409 response.

---

## Condensed Summaries

**Five-bullet summary**
- The Supplier Quality Copilot is a distributed multi-agent system: a Coordinator plus RAG, Traceability, Process/Maintenance and Logistics services (FastAPI, over a shared Pydantic contract) and a Streamlit UI, orchestrated by hand-written Python with no framework.
- One OEM complaint triggers extraction, dynamic routing and a two-phase dispatch in which Traceability's suspect population scopes the Process and Logistics agents. On the demo complaint it isolates 19 suspect units (18/19 = 95% Marginal/Fail vs a 30% baseline) and splits them 6 / 2 / 11 across plant, in transit and delivered.
- Every operational action (hold, shipment block, 100% sort, work order, OEM notification, 8D update, material release) waits for explicit approval. Re-run on 2026-09-21, the audit log shows zero executions before any approval, and an audit-driven fix now makes the server refuse decisions on non-pending actions (409), where it previously allowed a rejected action to be approved.
- It degrades gracefully: with 1 or 2 agents down the workflow still returns HTTP 200, marks the agents unavailable, lists evidence gaps, and still produces a consolidated result and an 8D draft. It also runs end to end with no LLM key, using offline extraction and embeddings.
- What remains open: the RAG eval is a small tuning set (7/7 pass), conflict detection can't be shown end to end, approver identity is self-declared, and there are no automated tests or CI.

**Three-bullet summary**
- A Tier-1 supplier-quality copilot: five independently deployable FastAPI agents plus a Streamlit UI that investigate an OEM steering-lamp complaint over cited RAG, production traceability, process data and containment logistics.
- It traces 19 suspect units at 95% vs a 30% baseline, holds every action for human approval (0 executions before approval, state machine enforced server-side), tolerates dead agents, and writes a full correlation-ID audit trail and an 8D draft.
- The open items are stated plainly: RAG eval breadth, an end-to-end conflict demo, authenticated approvers, and tests and CI.

**One-line description**

Built a Tier-1 supplier-quality copilot: a hand-orchestrated multi-agent system (FastAPI · LangChain/FAISS RAG · SQLite/pandas · Streamlit · Docker Compose) that turns an OEM steering-lamp complaint into a cited, scoped investigation (19 suspect units at 95% vs a 30% baseline), holds every containment action for human approval with a server-enforced state machine, degrades gracefully when agents fail, and drafts an 8D with a correlation-ID audit trail.

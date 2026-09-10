# Supplier Quality Copilot

A distributed multi-agent system for an automotive Tier-1 supplier: submit an
OEM quality complaint about an EPS (Electronic Power Steering) module, and a
Coordinator agent dynamically dispatches a Quality RAG agent, a
Traceability agent, and (conditionally) a Process/Maintenance agent and a
Logistics/Containment agent — over plain REST — then consolidates their
findings, surfaces conflicts between agents, and holds every operational
action for explicit human approval before it executes. Every step is
recorded in an audit log keyed by `correlation_id`.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the system diagram and data
flow, [`MESSAGE_CONTRACT.md`](MESSAGE_CONTRACT.md) for the full API/message
contract, and [`DEMO.md`](DEMO.md) for a step-by-step walkthrough script.

## Repository layout

```
coordinator-agent/        FastAPI -- orchestration, extraction, consolidation, 8D
quality-rag-agent/        FastAPI + FAISS -- controlled-document retrieval
traceability-agent/       FastAPI + SQLite -- suspect population analysis
process-maintenance-agent/ FastAPI -- control-plan deviation analysis
logistics-agent/          FastAPI -- containment quantity/command generation
frontend/                 Streamlit UI
shared/                   Message schema, auth, http client, audit log, LLM factory
data/docs/                6 synthetic controlled documents
data/manufacturing/       Synthetic production/alarm/calibration/maintenance/
                           inventory/shipment CSVs + generator script + SQLite DB
rag_eval/                 RAG evaluation script (5+ test questions)
sample_run/               One saved example run: 8D output (md+json), full
                           incident bundle, and audit log
docker-compose.yml
```

## Quick start

**Requirements:** Docker + Docker Compose.

```bash
docker compose up --build
```

Then open **http://localhost:8501** for the frontend. The Coordinator API is
at `http://localhost:8000` (see `MESSAGE_CONTRACT.md`); each agent is also
exposed directly for debugging (RAG `:8001`, Traceability `:8002`,
Process/Maintenance `:8003`, Logistics `:8004`).

### Configuring an LLM provider

The system works with **no API key configured** — every LLM call (incident
extraction, RAG interpretation, RAG embeddings) has a deterministic
rule-based or offline fallback (see "LLM provider swappability" below), so
`docker compose up --build` works out of the box. To use a real LLM, set
environment variables before `docker compose up` (or in a `.env` file next
to `docker-compose.yml`):

```bash
export LLM_PROVIDER=google        # or "openai" or "anthropic"
export GOOGLE_API_KEY=...         # matching key for the chosen provider
```

Supported: `google` (Gemini, via `langchain-google-genai`), `openai` (via
`langchain-openai`). `anthropic` is supported for generation but has no
first-party embeddings API, so the RAG agent's embeddings fall back to the
offline mock embedder in that mode — noted in code (`shared/llm.py`).

### Running components locally (without Docker)

Each service can run standalone with `uvicorn app:app --port <port>` from
its directory (after `pip install -r requirements.txt`); point the
Coordinator at the others via `RAG_AGENT_URL`, `TRACEABILITY_AGENT_URL`,
`PROCESS_MAINTENANCE_AGENT_URL`, `LOGISTICS_AGENT_URL` env vars (default to
`http://localhost:<port>` when unset — see `coordinator-agent/orchestration.py`).
The manufacturing SQLite DB is pre-generated at
`data/manufacturing/manufacturing.db`; to regenerate it:

```bash
cd data/manufacturing && python generate_data.py
```

## RAG design (chunking, metadata, retrieval)

See the full writeup in [`quality-rag-agent/ingest.py`](quality-rag-agent/ingest.py)'s
module docstring; summary:

- **Chunking:** Markdown headers (`#` document title, `##` section) are
  split first via `MarkdownHeaderTextSplitter` so every chunk keeps a
  `document` + `section` in its metadata (what lets `/retrieve` cite "doc
  name + section"), then each header-defined section is further split with
  `RecursiveCharacterTextSplitter` (chunk_size=800, chunk_overlap=120) so
  individual chunks stay focused.
- **Metadata schema:** `{document, section, source_file}` per chunk.
- **Retrieval:** FAISS, `similarity_search_with_score` (L2 distance),
  converted to a 0–1 relevance heuristic; top_k=4 (from a candidate pool of
  15, so PFMEA/control-plan-specific findings can be filtered separately).
  Below a tuned relevance floor, the agent returns
  `no_evidence_found: true` instead of asserting a weak match.
- **Evidence vs. interpretation:** always two separate response fields —
  see `MESSAGE_CONTRACT.md`.

Run the eval script: `python rag_eval/eval_rag.py` (auto-detects whether
the live service is reachable at `RAG_AGENT_URL`/`http://localhost:8001`,
else evaluates in-process against the same retrieval code).

## Key assumptions

- **No real OEM/MES/ERP/QMS integration** — all production, inventory, and
  document data is synthetic, generated once by
  `data/manufacturing/generate_data.py` and checked into the repo (both as
  CSVs and a pre-built `manufacturing.db`).
- **Date ranges map directly to production timestamps.** The take-home
  mentions optionally back-calculating a production window from a vehicle
  build date/VIN; this system takes the complaint's stated (or extracted)
  date range and queries production timestamps directly — VIN→build-date
  back-calculation is not implemented.
- **Default date range when unspecified:** since the synthetic dataset's
  production window is fixed (2025-04-20 to 2025-05-20) independent of
  wall-clock time, unspecified date ranges default to `2025-05-01` to
  `2025-05-20` (inside the injected fault window) rather than "last 30
  days from today" — documented in `coordinator-agent/extraction.py`.
- **One customer/OEM ("Northbridge Motors") and one part family
  ("EPS-2200")** in the synthetic dataset; extraction defaults to these
  when the complaint text doesn't clearly state otherwise.
- **Coordinator-native pseudo-actions:** `oem_notification` and
  `8d_update` are proposed and approved like any other action, but execute
  directly in the Coordinator (flip to `executed`) rather than dispatching
  to a dedicated agent, since no OEM-communications agent is in this
  system's scope.
- **Incident state is in-memory** in the Coordinator (`INCIDENTS: dict`),
  not persisted to a database — acceptable for a take-home demo, but state
  is lost on Coordinator restart (the audit log, on a shared volume, is
  the one thing that does survive).
- **Audit log is a shared SQLite file on a Docker volume**, written by
  every service directly (not proxied through the Coordinator), so the
  full cross-service trail is visible even if the Coordinator is restarted
  mid-incident.

## Known limitations

- Retrieval relevance scoring is a hand-tuned heuristic (L2-distance-based),
  not a calibrated probability. Real embedding providers (OpenAI/Google) and
  the offline mock embedder produce relevance scores on different scales, so
  `quality-rag-agent` uses two empirically-tuned floors
  (`RELEVANCE_FLOOR_REAL_EMBEDDINGS=0.45`, `RELEVANCE_FLOOR_MOCK_EMBEDDINGS=0.40`
  in `app.py`), selected automatically at startup based on which embedder
  actually initialized — both were validated against `rag_eval/eval_rag.py`'s
  on-topic/off-topic queries (7/7 pass on both). Either floor would need
  re-tuning for a larger document corpus.
- The offline mock embedder (used when no LLM provider key is configured
  or the configured key fails) is a hashed bag-of-words model with basic
  stopword filtering — meaningfully weaker semantically than a real
  embedding model, though its dedicated relevance floor keeps it correctly
  declining off-topic queries in the current eval set.
- `process-maintenance-agent`'s calibration-gap check (flagging a machine
  whose force-cell calibration is >30 days overdue) is implemented but
  doesn't trigger in the current synthetic dataset — the injected fault is
  instead evidenced by `FORCE_LOW` alarms, a `Fail - Recalibrated`
  calibration record, and a maintenance log entry, which is sufficient to
  tell a coherent root-cause story without that specific check firing.
- No persistence layer for incidents/approvals beyond the audit log and
  in-process memory — a Coordinator restart loses in-flight incident state
  (proposed actions, consolidated findings) though the audit trail for
  work already done remains queryable.
- Conflict detection (`consolidation.py::detect_conflicts`) is a targeted
  heuristic for one specific, deliberately-constructed scenario (a
  historical firmware-defect precedent vs. current connector-force
  evidence) rather than a general contradiction-detection engine.

## Explicitly out of scope

Per the take-home's scope: real OEM/vehicle data, real MES/ERP/QMS/CMMS/EDI
integration, direct PLC/equipment control, production-grade security
(the shared `X-API-Key` header is a simplified stand-in for real
service-to-service auth), Kubernetes, full root-cause validation (D5–D7 of
the 8D process), autonomous material release without approval, and
polished enterprise UI design.

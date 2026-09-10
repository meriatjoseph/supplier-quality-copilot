"""
Customer Quality RAG Agent.

Retrieves passages from the 6 controlled documents (CSR, control plan,
PFMEA, EOL procedure, traceability/containment procedure, prior 8D) via
FAISS, and separately generates an LLM interpretation of what the
retrieved evidence implies -- evidence and interpretation are always kept
in distinct response fields (see README "RAG design" section).
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.audit import log_event  # noqa: E402
from shared.auth import verify_api_key  # noqa: E402
from shared.dedup import TaskDedupStore  # noqa: E402
from shared.llm import get_chat_model  # noqa: E402
from shared.schema import ActionStatus, AgentMessage, AgentResponse  # noqa: E402

from ingest import build_vectorstore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("quality-rag-agent")

SERVICE_NAME = "quality-rag-agent"
TOP_K = 4
CANDIDATE_K = 15
# Heuristic 0-1 relevance floor below which we report "no supporting evidence found"
# rather than assert a weak match. Real embedding providers (OpenAI/Google) and the
# offline MockEmbeddings fallback produce relevance scores on different scales --
# both floors were empirically tuned against this repo's 6-document corpus using
# rag_eval/eval_rag.py's on-topic/off-topic test queries (see README "RAG design").
RELEVANCE_FLOOR_REAL_EMBEDDINGS = 0.45
RELEVANCE_FLOOR_MOCK_EMBEDDINGS = 0.40

app = FastAPI(title="Quality RAG Agent")
dedup_store = TaskDedupStore()

_vectorstore = None
RELEVANCE_FLOOR = RELEVANCE_FLOOR_REAL_EMBEDDINGS  # overwritten at startup based on actual embedder used


@app.on_event("startup")
def _startup():
    global _vectorstore, RELEVANCE_FLOOR
    logger.info("Building FAISS vectorstore from controlled documents...")
    _vectorstore, used_mock = build_vectorstore()
    RELEVANCE_FLOOR = RELEVANCE_FLOOR_MOCK_EMBEDDINGS if used_mock else RELEVANCE_FLOOR_REAL_EMBEDDINGS
    logger.info(
        "Vectorstore ready with %d chunks (used_mock_embeddings=%s, relevance_floor=%.2f)",
        _vectorstore.index.ntotal, used_mock, RELEVANCE_FLOOR,
    )


@app.get("/health")
def health():
    return {
        "service": SERVICE_NAME,
        "status": "ok" if _vectorstore is not None else "starting",
        "chunks_indexed": _vectorstore.index.ntotal if _vectorstore is not None else 0,
    }


def _score_to_relevance(distance: float) -> float:
    """Convert FAISS L2 distance to a rough 0-1 relevance heuristic (higher = better)."""
    return 1.0 / (1.0 + max(float(distance), 0.0))


def _search(query: str, k: int) -> list[dict]:
    raw = _vectorstore.similarity_search_with_score(query, k=k)
    out = []
    for doc, distance in raw:
        out.append(
            {
                "document": doc.metadata.get("document", "Unknown Document"),
                "section": doc.metadata.get("section", "General"),
                "content": doc.page_content,
                "relevance": round(_score_to_relevance(distance), 3),
            }
        )
    return out


def _confidence_label(top_relevance: float) -> str:
    if top_relevance >= 0.45:
        return "high"
    if top_relevance >= RELEVANCE_FLOOR:
        return "medium"
    return "low"


def _generate_interpretation(query: str, symptom: str, evidence: list[dict]) -> str:
    if not evidence:
        return "No supporting evidence found for this query -- no interpretation generated."

    chat = get_chat_model(temperature=0.0)
    context = "\n\n".join(
        f"[{e['document']} - {e['section']}]\n{e['content']}" for e in evidence
    )
    if chat is None:
        # Rule-based fallback so the agent still returns a useful (if terse)
        # interpretation when no LLM provider key is configured.
        docs = sorted({e["document"] for e in evidence})
        return (
            f"(rule-based fallback, no LLM configured) Retrieved passages from {', '.join(docs)} "
            f"appear relevant to the query '{query}'"
            + (f" and symptom '{symptom}'" if symptom else "")
            + ". Review the cited sections directly for applicable requirements."
        )

    prompt = (
        "You are a supplier-quality analyst assistant. You are given passages retrieved "
        "from controlled quality documents (customer requirements, control plan, PFMEA, "
        "EOL test procedure, traceability procedure, and a prior 8D report) relevant to an "
        "OEM complaint.\n\n"
        f"Complaint query: {query}\n"
        f"Symptom: {symptom or 'not specified'}\n\n"
        f"Retrieved passages:\n{context}\n\n"
        "Write a concise (3-5 sentence) interpretation of what these passages imply for this "
        "investigation: which requirements/controls are applicable, and what they suggest the "
        "team should check next. Clearly this is YOUR interpretation, not a verbatim quote -- "
        "do not fabricate requirements not supported by the passages above. If the passages "
        "are contradictory or insufficient to draw a conclusion, say so explicitly."
    )
    try:
        resp = chat.invoke(prompt)
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM interpretation call failed (%s), using rule-based fallback", exc)
        docs = sorted({e["document"] for e in evidence})
        return (
            f"(rule-based fallback, LLM call failed) Retrieved passages from {', '.join(docs)} "
            f"appear relevant to the query '{query}'"
            + (f" and symptom '{symptom}'" if symptom else "")
            + ". Review the cited sections directly for applicable requirements."
        )


def handle_retrieve_requirements(payload: dict) -> dict:
    query = payload.get("query", "")
    symptom = payload.get("symptom", "")
    top_k = int(payload.get("top_k", TOP_K))

    if not query.strip():
        return {
            "query": query,
            "evidence": [],
            "pfmea_control_plan_findings": [],
            "interpretation": "No query provided.",
            "confidence": "none",
            "no_evidence_found": True,
        }

    candidates = _search(query, k=CANDIDATE_K)
    evidence = [c for c in candidates if c["relevance"] >= RELEVANCE_FLOOR][:top_k]

    pfmea_cp = [
        c for c in candidates
        if any(kw in c["document"].lower() for kw in ["pfmea", "control plan"])
        and c["relevance"] >= RELEVANCE_FLOOR
    ][:top_k]

    no_evidence = len(evidence) == 0
    top_relevance = evidence[0]["relevance"] if evidence else (candidates[0]["relevance"] if candidates else 0.0)
    confidence = "none" if no_evidence else _confidence_label(top_relevance)

    interpretation = (
        "No supporting evidence found for this query in the controlled document set. "
        "Do not assume a requirement exists -- escalate to Quality Engineering for manual review."
        if no_evidence
        else _generate_interpretation(query, symptom, evidence)
    )

    return {
        "query": query,
        "evidence": evidence,
        "pfmea_control_plan_findings": pfmea_cp,
        "interpretation": interpretation,
        "confidence": confidence,
        "no_evidence_found": no_evidence,
    }


@app.post("/invoke", response_model=AgentResponse, dependencies=[Depends(verify_api_key)])
def invoke(message: AgentMessage):
    cached = dedup_store.get(message.task_id)
    if cached is not None:
        logger.info("Duplicate task_id %s detected, returning cached response", message.task_id)
        return AgentResponse(**cached)

    log_event(
        correlation_id=message.correlation_id, event_type="dispatch_received",
        incident_id=message.incident_id, task_id=message.task_id,
        sender=message.sender, recipient=SERVICE_NAME, action=message.action,
        status="received",
    )

    start = time.perf_counter()
    if message.action == "retrieve_requirements":
        result = handle_retrieve_requirements(message.payload)
        status = ActionStatus.OK
        error = None
    else:
        result = {}
        status = ActionStatus.ERROR
        error = f"Unknown action '{message.action}' for {SERVICE_NAME}"

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    response = AgentResponse(
        incident_id=message.incident_id, task_id=message.task_id,
        correlation_id=message.correlation_id, sender=SERVICE_NAME, recipient=message.sender,
        action=message.action, status=status, result=result, error=error, duration_ms=duration_ms,
    )
    dedup_store.put(message.task_id, response.model_dump())

    log_event(
        correlation_id=message.correlation_id, event_type="response_sent",
        incident_id=message.incident_id, task_id=message.task_id,
        sender=SERVICE_NAME, recipient=message.sender, action=message.action,
        status=status.value, detail={"confidence": result.get("confidence")},
    )
    return response


class DirectRetrieveRequest(BaseModel):
    query: str
    symptom: str = ""
    top_k: int = TOP_K


@app.post("/retrieve", dependencies=[Depends(verify_api_key)])
def retrieve_direct(req: DirectRetrieveRequest):
    """Direct retrieval endpoint (not via the AgentMessage envelope) for eval/debugging."""
    return handle_retrieve_requirements(req.model_dump())

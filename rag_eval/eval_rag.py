"""
RAG evaluation script for the Customer Quality RAG Agent.

Runs a fixed set of test questions, each with an expected source
document/section, against the RAG agent and reports whether the actual
top retrieved passage cites the expected document (and ideally section),
plus whether the "no evidence found" cases behave as expected.

Usage:
    python eval_rag.py                # runs against the live service at RAG_AGENT_URL
                                       # if reachable, else falls back to in-process import
    RAG_AGENT_URL=http://localhost:8001 python eval_rag.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAG_AGENT_URL = os.environ.get("RAG_AGENT_URL", "http://localhost:8001")
API_KEY = os.environ.get("SHARED_API_KEY", "dev-shared-secret-change-me")

TEST_CASES = [
    {
        "query": "What is the connector insertion force specification and reaction plan?",
        "expected_document_contains": ["Control Plan"],
        "expected_section_contains": "Connector Insertion Force",
        "expect_no_evidence": False,
    },
    {
        # Contact-resistance acceptance/disposition content legitimately appears
        # in the EOL procedure, the control plan's EOL control-characteristic
        # section, and the PFMEA's "Marginal result accepted without proper
        # disposition" failure mode -- any of these is a correct citation.
        "query": "What is the acceptance criteria and disposition for EOL contact resistance results?",
        "expected_document_contains": ["End-of-Line", "Control Plan", "PFMEA"],
        "expected_section_contains": None,
        "expect_no_evidence": False,
    },
    {
        # Any section of the prior 8D report is acceptable evidence for this query;
        # what matters is retrieving the correct document.
        "query": "What was the root cause of the prior 2023 intermittent steering warning lamp complaint?",
        "expected_document_contains": ["8D Report"],
        "expected_section_contains": None,
        "expect_no_evidence": False,
    },
    {
        "query": "What are the 8D corrective action timing requirements for Class A safety complaints?",
        "expected_document_contains": ["Customer-Specific Requirements"],
        "expected_section_contains": "8D",
        "expect_no_evidence": False,
    },
    {
        "query": "What is the highest RPN failure mode in the PFMEA related to connector insertion?",
        "expected_document_contains": ["PFMEA"],
        "expected_section_contains": None,  # RPN 180 appears in Section 1 and is referenced in Section 5
        "expect_no_evidence": False,
    },
    {
        # Both the CSR and the Traceability/Containment procedure state this
        # requirement; either is a legitimate citation.
        "query": "What must the supplier do before contacting dealers or end customers during containment?",
        "expected_document_contains": ["Traceability and Containment", "Customer-Specific Requirements"],
        "expected_section_contains": None,
        "expect_no_evidence": False,
    },
    {
        "query": "What is the recommended tire pressure for the vehicle?",
        "expected_document_contains": None,
        "expected_section_contains": None,
        "expect_no_evidence": True,
    },
]


def _run_via_http(query: str) -> dict:
    import httpx

    resp = httpx.post(
        f"{RAG_AGENT_URL}/retrieve",
        json={"query": query},
        headers={"X-API-Key": API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _run_in_process(query: str) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "quality-rag-agent"))
    import app as rag_app  # noqa: PLC0415

    if rag_app._vectorstore is None:  # not started via uvicorn lifecycle -- build directly
        from ingest import build_vectorstore  # noqa: PLC0415

        rag_app._vectorstore, used_mock = build_vectorstore()
        rag_app.RELEVANCE_FLOOR = (
            rag_app.RELEVANCE_FLOOR_MOCK_EMBEDDINGS if used_mock else rag_app.RELEVANCE_FLOOR_REAL_EMBEDDINGS
        )
    return rag_app.handle_retrieve_requirements({"query": query})


def run_case(case: dict, use_http: bool) -> dict:
    query = case["query"]
    try:
        result = _run_via_http(query) if use_http else _run_in_process(query)
    except Exception as exc:  # noqa: BLE001
        return {"query": query, "passed": False, "detail": f"ERROR calling RAG agent: {exc}"}

    if case["expect_no_evidence"]:
        passed = result.get("no_evidence_found") is True
        detail = f"no_evidence_found={result.get('no_evidence_found')}"
        return {"query": query, "passed": passed, "detail": detail, "result": result}

    evidence = result.get("evidence", [])
    if not evidence:
        return {"query": query, "passed": False, "detail": "no evidence returned (expected some)", "result": result}

    top = evidence[0]
    expected_docs = case["expected_document_contains"]
    if expected_docs is None:
        doc_ok = True
    else:
        if isinstance(expected_docs, str):
            expected_docs = [expected_docs]
        doc_ok = any(d.lower() in top["document"].lower() for d in expected_docs)
    sec_ok = case["expected_section_contains"] is None or case["expected_section_contains"].lower() in top["section"].lower()
    passed = doc_ok and sec_ok
    detail = f"top result -> document='{top['document']}', section='{top['section']}', relevance={top['relevance']}"
    return {"query": query, "passed": passed, "detail": detail, "result": result}


def main():
    use_http = True
    try:
        import httpx

        httpx.get(f"{RAG_AGENT_URL}/health", timeout=2)
    except Exception:
        use_http = False
        print(f"RAG agent not reachable at {RAG_AGENT_URL} -- falling back to in-process evaluation.\n")

    print(f"Running {len(TEST_CASES)} RAG eval cases ({'HTTP' if use_http else 'in-process'})...\n")
    results = []
    for i, case in enumerate(TEST_CASES, start=1):
        r = run_case(case, use_http)
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] #{i}: {r['query']}")
        print(f"        {r['detail']}\n")

    n_pass = sum(1 for r in results if r["passed"])
    print(f"Summary: {n_pass}/{len(results)} passed.")
    if n_pass < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()

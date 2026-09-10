"""
LLM-based structured extraction of a free-text OEM complaint into
customer / part_number / symptom / date range / urgency, with a
deterministic keyword/regex fallback used whenever no LLM provider is
configured or the provider call fails (e.g. invalid/missing API key) --
the Coordinator must never hard-fail just because extraction couldn't
reach an LLM.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.llm import get_chat_model  # noqa: E402
from shared.schema import ExtractedIncident  # noqa: E402

logger = logging.getLogger("coordinator.extraction")

# Demo dataset production window is fixed in synthetic time (April-May 2025),
# independent of wall-clock "today" -- when the complaint doesn't specify
# dates, default to the window that overlaps the injected fault pattern so
# the downstream traceability/process analysis has something meaningful to
# work with. This is documented as an assumption in the README.
DEFAULT_DATE_RANGE_START = "2025-05-01"
DEFAULT_DATE_RANGE_END = "2025-05-20"

KNOWN_CUSTOMER = "Northbridge Motors"
KNOWN_PART_NUMBERS = ["EPS-2200-A", "EPS-2200-B", "EPS-2200"]


def _extract_json_block(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).rstrip("`").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(text[start : end + 1])


def _rule_based_extract(complaint_text: str) -> ExtractedIncident:
    text_lower = complaint_text.lower()

    customer = KNOWN_CUSTOMER
    m = re.search(r"(?:from|customer[:\s]+)([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})", complaint_text)
    if m:
        customer = m.group(1).strip()

    part_number = None
    for pn in KNOWN_PART_NUMBERS:
        if pn.lower() in text_lower:
            part_number = pn
            break
    if part_number is None:
        m = re.search(r"\b([A-Z]{2,6}-\d{3,5}(?:-[A-Z])?)\b", complaint_text)
        part_number = m.group(1) if m else "EPS-2200-A"

    dates = re.findall(r"\d{4}-\d{2}-\d{2}", complaint_text)
    date_start = dates[0] if len(dates) >= 1 else DEFAULT_DATE_RANGE_START
    date_end = dates[1] if len(dates) >= 2 else (dates[0] if len(dates) == 1 else DEFAULT_DATE_RANGE_END)

    urgency = "medium"
    if any(k in text_lower for k in ["critical", "urgent", "safety", "immediately", "asap", "stop ship"]):
        urgency = "high"
    elif any(k in text_lower for k in ["minor", "low priority", "fyi"]):
        urgency = "low"

    symptom_keywords = ["steering warning", "warning lamp", "warning light", "loss of assist", "intermittent"]
    symptom = next((kw for kw in symptom_keywords if kw in text_lower), None)
    if symptom is None:
        # Fall back to a trimmed version of the complaint itself.
        symptom = complaint_text.strip()[:160]
    else:
        symptom = complaint_text.strip()[:200]  # keep fuller context, not just the matched keyword

    return ExtractedIncident(
        customer=customer,
        part_number=part_number,
        symptom=symptom,
        date_range_start=date_start,
        date_range_end=date_end,
        urgency=urgency,
        raw_complaint=complaint_text,
    )


def extract_incident(complaint_text: str) -> ExtractedIncident:
    chat = get_chat_model(temperature=0.0)
    if chat is None:
        logger.info("No LLM provider configured; using rule-based extraction fallback.")
        return _rule_based_extract(complaint_text)

    prompt = (
        "Extract the following fields from this OEM automotive quality complaint as a JSON object "
        "with EXACTLY these keys: customer, part_number, symptom, date_range_start, date_range_end, "
        "urgency.\n"
        "- customer: the OEM/customer name mentioned (if none mentioned, use 'Northbridge Motors').\n"
        "- part_number: the part number mentioned (e.g. 'EPS-2200-A'); if unclear use 'EPS-2200-A'.\n"
        "- symptom: a concise 1-sentence description of the reported symptom.\n"
        "- date_range_start / date_range_end: production or field date range in YYYY-MM-DD format if "
        f"mentioned, otherwise use '{DEFAULT_DATE_RANGE_START}' and '{DEFAULT_DATE_RANGE_END}'.\n"
        "- urgency: one of 'low', 'medium', 'high', 'critical' based on the tone/content.\n\n"
        f"Complaint:\n{complaint_text}\n\n"
        "Respond with ONLY the JSON object, no other text."
    )
    try:
        resp = chat.invoke(prompt)
        content = resp.content if hasattr(resp, "content") else str(resp)
        data = _extract_json_block(content)
        data["raw_complaint"] = complaint_text
        data.setdefault("customer", KNOWN_CUSTOMER)
        data.setdefault("part_number", "EPS-2200-A")
        data.setdefault("date_range_start", DEFAULT_DATE_RANGE_START)
        data.setdefault("date_range_end", DEFAULT_DATE_RANGE_END)
        data.setdefault("urgency", "medium")
        return ExtractedIncident(**data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM extraction failed (%s); falling back to rule-based extraction.", exc)
        return _rule_based_extract(complaint_text)

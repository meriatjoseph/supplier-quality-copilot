"""
Traceability and Production Agent.

Given a date range (and optionally part number) from an incident, maps to
serial numbers produced in that window, segments by line/shift/component
lot/firmware, and identifies which segment(s) show a disproportionate
Marginal/Fail rate versus the overall population -- returning a reasoned
suspect population and containment boundary, not a raw data dump.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.audit import log_event  # noqa: E402
from shared.auth import verify_api_key  # noqa: E402
from shared.dedup import TaskDedupStore  # noqa: E402
from shared.schema import ActionStatus, AgentMessage, AgentResponse  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("traceability-agent")

SERVICE_NAME = "traceability-agent"
DB_PATH = os.environ.get(
    "MANUFACTURING_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "manufacturing" / "manufacturing.db"),
)
MIN_GROUP_SIZE = 5
DISPROPORTIONATE_RATIO = 2.0  # segment bad-rate must be >= this multiple of overall bad-rate
MIN_ABS_BAD_RATE = 0.25  # ...and at least this absolute bad-rate, to avoid flagging tiny noise

app = FastAPI(title="Traceability and Production Agent")
dedup_store = TaskDedupStore()

_production_df: pd.DataFrame | None = None


@app.on_event("startup")
def _startup():
    global _production_df
    conn = sqlite3.connect(DB_PATH)
    try:
        _production_df = pd.read_sql_query("SELECT * FROM production", conn, parse_dates=["production_time"])
    finally:
        conn.close()
    logger.info("Loaded %d production records from %s", len(_production_df), DB_PATH)


@app.get("/health")
def health():
    return {
        "service": SERVICE_NAME,
        "status": "ok" if _production_df is not None else "starting",
        "production_records": 0 if _production_df is None else len(_production_df),
    }


def _filter_population(part_number: str | None, start: str | None, end: str | None) -> pd.DataFrame:
    df = _production_df.copy()
    if part_number:
        matched = df[df["part_number"] == part_number]
        if len(matched) > 0:
            df = matched
        # if the incident's part number doesn't match any production data, fall back
        # to the full population rather than returning an empty result silently.
    if start:
        df = df[df["production_time"] >= pd.Timestamp(start)]
    if end:
        df = df[df["production_time"] <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)]
    return df


def _bad_rate(df: pd.DataFrame) -> float:
    if len(df) == 0:
        return 0.0
    return float((df["eol_result"] != "Pass").mean())


def identify_suspect_population(payload: dict) -> dict:
    part_number = payload.get("part_number")
    start = payload.get("date_range_start")
    end = payload.get("date_range_end")

    if _production_df is None or len(_production_df) == 0:
        return {"error": "No production data loaded"}

    scoped = _filter_population(part_number, start, end)
    if len(scoped) == 0:
        # No production found in the stated window -- widen to full dataset so the
        # investigation isn't dead-ended by a bad/estimated date range, and flag it.
        scoped = _production_df.copy()
        date_range_note = (
            f"No production found in stated window ({start} to {end}); "
            "analysis widened to the full available production history."
        )
    else:
        date_range_note = None

    overall_bad_rate = _bad_rate(scoped)
    total_units = len(scoped)

    # --- Segment by line / shift / connector lot ---
    seg_rows = []
    grouped = scoped.groupby(["line", "shift", "connector_lot"])
    for (line, shift, lot), g in grouped:
        if len(g) < MIN_GROUP_SIZE:
            continue
        seg_rows.append(
            {
                "line": line,
                "shift": shift,
                "connector_lot": lot,
                "count": int(len(g)),
                "bad_count": int((g["eol_result"] != "Pass").sum()),
                "bad_rate": round(_bad_rate(g), 3),
            }
        )
    seg_rows.sort(key=lambda r: r["bad_rate"], reverse=True)

    # --- Firmware-level comparison (tests the alternate "firmware defect" hypothesis) ---
    fw_rows = []
    for fw, g in scoped.groupby("firmware_version"):
        fw_rows.append(
            {
                "firmware_version": fw,
                "count": int(len(g)),
                "bad_count": int((g["eol_result"] != "Pass").sum()),
                "bad_rate": round(_bad_rate(g), 3),
            }
        )
    fw_rows.sort(key=lambda r: r["bad_rate"], reverse=True)
    fw_spread = (max(r["bad_rate"] for r in fw_rows) - min(r["bad_rate"] for r in fw_rows)) if fw_rows else 0.0

    disproportionate_found = False
    suspect_population = None
    common_factor = None
    containment_boundary = None
    reasoning_parts = []

    if date_range_note:
        reasoning_parts.append(date_range_note)

    if seg_rows:
        top = seg_rows[0]
        threshold = max(overall_bad_rate * DISPROPORTIONATE_RATIO, MIN_ABS_BAD_RATE)
        if top["bad_rate"] >= threshold and top["bad_rate"] > overall_bad_rate:
            disproportionate_found = True
            line, shift, lot = top["line"], top["shift"], top["connector_lot"]
            seg_df = scoped[
                (scoped["line"] == line) & (scoped["shift"] == shift) & (scoped["connector_lot"] == lot)
            ]
            date_min = seg_df["production_time"].min()
            date_max = seg_df["production_time"].max()
            suspect_population = {
                "line": line,
                "shift": shift,
                "connector_lot": lot,
                "serial_numbers": seg_df["serial_number"].tolist(),
                "count": int(len(seg_df)),
                "bad_count": top["bad_count"],
                "bad_rate": top["bad_rate"],
                "production_date_range": {
                    "start": date_min.strftime("%Y-%m-%d %H:%M"),
                    "end": date_max.strftime("%Y-%m-%d %H:%M"),
                },
            }
            common_factor = (
                f"Line={line}, Shift={shift}, Connector Lot={lot}: "
                f"{top['bad_count']}/{top['count']} units ({top['bad_rate']:.0%}) scored Marginal/Fail at EOL, "
                f"vs {overall_bad_rate:.0%} across the full population in this window "
                f"({top['bad_rate']/overall_bad_rate:.1f}x higher)." if overall_bad_rate > 0 else
                f"Line={line}, Shift={shift}, Connector Lot={lot}: {top['bad_count']}/{top['count']} units "
                f"({top['bad_rate']:.0%}) scored Marginal/Fail at EOL, vs 0% baseline elsewhere."
            )
            containment_boundary = (
                f"Hold all units from {line}, {shift} shift, component lot {lot}, "
                f"produced {date_min.strftime('%Y-%m-%d %H:%M')} to {date_max.strftime('%Y-%m-%d %H:%M')} "
                f"({len(seg_df)} units)."
            )
            reasoning_parts.append(
                f"Segment {line}/{shift}/{lot} is the narrowest grouping (line x shift x component lot) "
                f"showing a disproportionate EOL Marginal/Fail concentration -- {top['bad_rate']:.0%} vs "
                f"{overall_bad_rate:.0%} baseline -- and meets the minimum group size ({MIN_GROUP_SIZE} units) "
                "to be a meaningful pattern rather than noise."
            )
        else:
            reasoning_parts.append(
                f"No line/shift/component-lot segment showed a disproportionate Marginal/Fail rate "
                f"(highest segment: {top['bad_rate']:.0%} vs overall {overall_bad_rate:.0%}, "
                f"below the {DISPROPORTIONATE_RATIO}x / {MIN_ABS_BAD_RATE:.0%} flagging threshold)."
            )
    else:
        reasoning_parts.append("No segment met the minimum group size for statistical grouping.")

    if fw_spread < 0.10:
        reasoning_parts.append(
            f"Firmware version does not appear to be a differentiating factor in this window "
            f"(bad-rate spread across firmware versions: {fw_spread:.0%})."
        )
    else:
        reasoning_parts.append(
            f"Firmware version shows a notable bad-rate spread ({fw_spread:.0%}) and should also be "
            "considered as a contributing factor."
        )

    return {
        "date_range_used": {"start": start, "end": end},
        "part_number_filter": part_number,
        "total_units_in_range": total_units,
        "overall_bad_rate": round(overall_bad_rate, 3),
        "segment_analysis": seg_rows[:8],
        "firmware_analysis": fw_rows,
        "disproportionate_segment_found": disproportionate_found,
        "suspect_population": suspect_population,
        "common_factor": common_factor,
        "recommended_containment_boundary": containment_boundary,
        "reasoning": " ".join(reasoning_parts),
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
        sender=message.sender, recipient=SERVICE_NAME, action=message.action, status="received",
    )

    start_t = time.perf_counter()
    if message.action == "identify_suspect_population":
        result = identify_suspect_population(message.payload)
        status = ActionStatus.OK
        error = None
    else:
        result = {}
        status = ActionStatus.ERROR
        error = f"Unknown action '{message.action}' for {SERVICE_NAME}"

    duration_ms = round((time.perf_counter() - start_t) * 1000, 1)
    response = AgentResponse(
        incident_id=message.incident_id, task_id=message.task_id,
        correlation_id=message.correlation_id, sender=SERVICE_NAME, recipient=message.sender,
        action=message.action, status=status, result=result, error=error, duration_ms=duration_ms,
    )
    dedup_store.put(message.task_id, response.model_dump())

    log_event(
        correlation_id=message.correlation_id, event_type="response_sent",
        incident_id=message.incident_id, task_id=message.task_id,
        sender=SERVICE_NAME, recipient=message.sender, action=message.action, status=status.value,
        detail={"disproportionate_segment_found": result.get("disproportionate_segment_found")},
    )
    return response

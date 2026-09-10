"""
Process and Maintenance Agent.

Compares actual machine parameters (connector insertion force readings from
the production genealogy) against control-plan limits (Document 02, Section
2: 45-65N), cross-references alarms/calibration/maintenance logs, flags
deviations in the relevant window, and proposes diagnostic checks plus a
work order -- held for human approval, never auto-created.
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
from shared.schema import ActionStatus, AgentMessage, AgentResponse, new_id  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("process-maintenance-agent")

SERVICE_NAME = "process-maintenance-agent"
DB_PATH = os.environ.get(
    "MANUFACTURING_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "manufacturing" / "manufacturing.db"),
)

# Control-plan limits (Document 02, Section 2) -- reused here rather than
# re-derived, per the take-home's instruction to define limits in the
# control-plan doc and reuse them in the process/maintenance agent.
FORCE_SPEC_MIN_N = 45.0
FORCE_SPEC_MAX_N = 65.0
CALIBRATION_CYCLE_DAYS = 30

app = FastAPI(title="Process and Maintenance Agent")
dedup_store = TaskDedupStore()

_production_df: pd.DataFrame | None = None
_alarms_df: pd.DataFrame | None = None
_calibration_df: pd.DataFrame | None = None
_maintenance_df: pd.DataFrame | None = None

# Proposed work orders held pending human approval, keyed by work_order_id.
_pending_work_orders: dict[str, dict] = {}


@app.on_event("startup")
def _startup():
    global _production_df, _alarms_df, _calibration_df, _maintenance_df
    conn = sqlite3.connect(DB_PATH)
    try:
        _production_df = pd.read_sql_query("SELECT * FROM production", conn, parse_dates=["production_time"])
        _alarms_df = pd.read_sql_query("SELECT * FROM alarms", conn, parse_dates=["alarm_time"])
        _calibration_df = pd.read_sql_query("SELECT * FROM calibration", conn, parse_dates=["calibration_date"])
        _maintenance_df = pd.read_sql_query("SELECT * FROM maintenance", conn, parse_dates=["date"])
    finally:
        conn.close()
    logger.info(
        "Loaded %d production, %d alarm, %d calibration, %d maintenance records from %s",
        len(_production_df), len(_alarms_df), len(_calibration_df), len(_maintenance_df), DB_PATH,
    )


@app.get("/health")
def health():
    return {
        "service": SERVICE_NAME,
        "status": "ok" if _production_df is not None else "starting",
    }


def _in_window(df: pd.DataFrame, col: str, start: str | None, end: str | None) -> pd.DataFrame:
    out = df
    if start:
        out = out[out[col] >= pd.Timestamp(start)]
    if end:
        out = out[out[col] <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)]
    return out


def _calibration_gap_check(machine_id: str, before: pd.Timestamp) -> dict | None:
    """Flags if a machine's calibration cycle exceeded CALIBRATION_CYCLE_DAYS before a given date."""
    m = _calibration_df[_calibration_df["machine_id"] == machine_id].sort_values("calibration_date")
    passing = m[m["result"] == "Pass"]
    prior = passing[passing["calibration_date"] <= before]
    if prior.empty:
        return None
    last_pass = prior["calibration_date"].max()
    gap_days = (before - last_pass).days
    if gap_days > CALIBRATION_CYCLE_DAYS:
        return {
            "machine_id": machine_id,
            "last_passing_calibration": last_pass.strftime("%Y-%m-%d"),
            "days_since_calibration": gap_days,
            "cycle_limit_days": CALIBRATION_CYCLE_DAYS,
        }
    return None


def analyze_process_deviations(payload: dict) -> dict:
    if _production_df is None:
        return {"error": "process/maintenance data not loaded"}

    start = payload.get("date_range_start")
    end = payload.get("date_range_end")
    line = payload.get("line")
    shift = payload.get("shift")
    connector_lot = payload.get("connector_lot")

    scoped = _in_window(_production_df, "production_time", start, end)
    if line:
        scoped = scoped[scoped["line"] == line]
    if shift:
        scoped = scoped[scoped["shift"] == shift]
    if connector_lot:
        scoped = scoped[scoped["connector_lot"] == connector_lot]

    deviations = []
    diagnostic_recommendations = []

    if len(scoped) > 0:
        out_of_spec = scoped[(scoped["connector_force_n"] < FORCE_SPEC_MIN_N) | (scoped["connector_force_n"] > FORCE_SPEC_MAX_N)]
        for machine_id, g in scoped.groupby("machine_id"):
            g_bad = g[(g["connector_force_n"] < FORCE_SPEC_MIN_N) | (g["connector_force_n"] > FORCE_SPEC_MAX_N)]
            if len(g_bad) == 0:
                continue
            pct = len(g_bad) / len(g)
            deviations.append(
                {
                    "parameter": "connector_insertion_force_n",
                    "machine_id": machine_id,
                    "spec_limits": {"min": FORCE_SPEC_MIN_N, "max": FORCE_SPEC_MAX_N, "unit": "N"},
                    "units_checked": int(len(g)),
                    "units_out_of_spec": int(len(g_bad)),
                    "out_of_spec_pct": round(pct, 3),
                    "mean_reading_out_of_spec_group": round(float(g_bad["connector_force_n"].mean()), 1),
                    "severity": "high" if pct >= 0.3 else ("medium" if pct >= 0.1 else "low"),
                }
            )

        for dev in deviations:
            machine_id = dev["machine_id"]
            window_end = pd.Timestamp(end) if end else scoped["production_time"].max()
            related_alarms = _alarms_df[
                (_alarms_df["machine_id"] == machine_id)
                & (_alarms_df["alarm_code"].str.contains("FORCE", na=False))
            ]
            related_alarms = _in_window(related_alarms, "alarm_time", start, end)
            dev["related_alarm_count"] = int(len(related_alarms))

            cal_gap = _calibration_gap_check(machine_id, window_end)
            dev["calibration_gap"] = cal_gap

            related_maint = _maintenance_df[_maintenance_df["machine_id"] == machine_id]
            related_maint = related_maint[
                (related_maint["date"] >= (window_end - pd.Timedelta(days=10))) & (related_maint["date"] <= (window_end + pd.Timedelta(days=10)))
            ]
            dev["related_maintenance_records"] = related_maint.to_dict(orient="records")

            rec = f"Machine {machine_id}: {dev['units_out_of_spec']}/{dev['units_checked']} units " \
                  f"({dev['out_of_spec_pct']:.0%}) had connector insertion force outside the " \
                  f"{FORCE_SPEC_MIN_N}-{FORCE_SPEC_MAX_N}N control-plan limit."
            if cal_gap:
                rec += f" Force-cell calibration was {cal_gap['days_since_calibration']} days overdue " \
                       f"(limit {CALIBRATION_CYCLE_DAYS} days) as of this window."
            if dev["related_alarm_count"] > 0:
                rec += f" {dev['related_alarm_count']} FORCE_LOW alarm(s) logged on this machine in-window."
            diagnostic_recommendations.append(
                {
                    "machine_id": machine_id,
                    "recommendation": rec,
                    "suggested_checks": [
                        "Recalibrate connector press force cell against certified reference standard.",
                        "Inspect/replace insertion tooling for wear.",
                        "Audit 30-day calibration cycle compliance for this machine.",
                        "Re-test contact resistance on affected units to confirm connector seating.",
                    ],
                    "temporary_process_control": (
                        f"Increase force-reading verification frequency on {machine_id} to every unit "
                        "(if not already 100%) and add a secondary operator visual check of connector "
                        "seating until recalibration is verified."
                    ),
                }
            )
    else:
        out_of_spec = scoped

    # Proposed work order -- held for human approval, not auto-created.
    proposed_work_order = None
    if deviations:
        top = max(deviations, key=lambda d: d["out_of_spec_pct"])
        wo_id = new_id("WO")
        proposed_work_order = {
            "work_order_id": wo_id,
            "work_order_type": "Corrective Maintenance",
            "machine_id": top["machine_id"],
            "description": (
                f"Recalibrate and inspect {top['machine_id']} connector press force cell/tooling. "
                f"{top['units_out_of_spec']} of {top['units_checked']} units in the investigation window "
                f"read outside the {FORCE_SPEC_MIN_N}-{FORCE_SPEC_MAX_N}N control-plan spec."
            ),
            "priority": "High" if top["severity"] == "high" else "Medium",
            "status": "awaiting_approval",
        }
        _pending_work_orders[wo_id] = proposed_work_order

    return {
        "date_range_used": {"start": start, "end": end},
        "scope_filters": {"line": line, "shift": shift, "connector_lot": connector_lot},
        "units_analyzed": int(len(scoped)),
        "total_units_out_of_spec": int(len(out_of_spec)) if len(scoped) > 0 else 0,
        "deviations": deviations,
        "diagnostic_recommendations": diagnostic_recommendations,
        "proposed_work_order": proposed_work_order,
    }


def execute_work_order(payload: dict) -> dict:
    """Only marks a work order executed after Coordinator relays human approval."""
    wo_id = payload.get("work_order_id")
    approved = payload.get("approved", False)
    wo = _pending_work_orders.get(wo_id)
    if wo is None:
        return {"error": f"Unknown work_order_id {wo_id}"}
    if not approved:
        return {"work_order_id": wo_id, "status": "rejected", "detail": "Human approval was not granted."}
    wo["status"] = "executed"
    return {"work_order_id": wo_id, "status": "executed", "work_order": wo}


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
    if message.action == "analyze_process_deviations":
        result = analyze_process_deviations(message.payload)
        status = ActionStatus.OK
        error = None
    elif message.action == "execute_work_order":
        result = execute_work_order(message.payload)
        status = ActionStatus.EXECUTED if result.get("status") == "executed" else ActionStatus.REJECTED
        error = result.get("error")
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
    )
    return response

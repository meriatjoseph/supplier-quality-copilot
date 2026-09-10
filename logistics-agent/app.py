"""
Logistics and Containment Agent.

Given the suspect population from Traceability, computes affected
quantities per location (Tier-1 plant / in-transit / third-party warehouse /
OEM) and proposes hold/sort/inspect/replace actions -- generating mock
inventory-hold and shipment-block command objects that are only marked
"executed" after the Coordinator relays explicit human approval.
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
logger = logging.getLogger("logistics-agent")

SERVICE_NAME = "logistics-agent"
DB_PATH = os.environ.get(
    "MANUFACTURING_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "manufacturing" / "manufacturing.db"),
)

app = FastAPI(title="Logistics and Containment Agent")
dedup_store = TaskDedupStore()

_inventory_df: pd.DataFrame | None = None
_shipments_df: pd.DataFrame | None = None

# Proposed containment commands held pending human approval, keyed by action_id.
_pending_actions: dict[str, dict] = {}


@app.on_event("startup")
def _startup():
    global _inventory_df, _shipments_df
    conn = sqlite3.connect(DB_PATH)
    try:
        _inventory_df = pd.read_sql_query("SELECT * FROM inventory", conn)
        _shipments_df = pd.read_sql_query("SELECT * FROM shipments", conn)
    finally:
        conn.close()
    logger.info("Loaded %d inventory rows, %d shipment rows from %s", len(_inventory_df), len(_shipments_df), DB_PATH)


@app.get("/health")
def health():
    return {
        "service": SERVICE_NAME,
        "status": "ok" if _inventory_df is not None else "starting",
    }


def assess_containment(payload: dict) -> dict:
    if _inventory_df is None:
        return {"error": "logistics data not loaded"}

    part_number = payload.get("part_number")
    suspect_serials = payload.get("suspect_serial_numbers", []) or []
    suspect_count = payload.get("suspect_count", len(suspect_serials))
    boundary_description = payload.get("containment_boundary_description", "")

    shipped = _shipments_df[_shipments_df["serial_number"].isin(suspect_serials)] if suspect_serials else _shipments_df.iloc[0:0]
    not_yet_shipped_count = max(suspect_count - len(shipped), 0)

    by_status_dest = (
        shipped.groupby(["status", "destination"]).size().reset_index(name="count").to_dict(orient="records")
        if len(shipped) > 0
        else []
    )
    in_transit_count = int((shipped["status"] == "In-Transit").sum())
    delivered_count = int((shipped["status"] == "Delivered").sum())

    plant_inventory = (
        _inventory_df[(_inventory_df["location_type"] == "plant") & (_inventory_df["part_number"] == part_number)]
        if part_number
        else _inventory_df[_inventory_df["location_type"] == "plant"]
    )
    plant_on_hand = int(plant_inventory["quantity_on_hand"].sum()) if len(plant_inventory) else 0

    affected_by_location = {
        "tier1_plant": {
            "estimated_suspect_units_on_hand": not_yet_shipped_count,
            "total_part_inventory_on_hand": plant_on_hand,
            "proposed_action": "inventory_hold",
        },
        "in_transit": {
            "suspect_units": in_transit_count,
            "proposed_action": "shipment_block",
        },
        "delivered_to_oem_or_warehouse": {
            "suspect_units": delivered_count,
            "breakdown_by_destination": by_status_dest,
            "proposed_action": "100_percent_sort_and_notify_oem",
        },
    }

    proposed_actions = []

    if not_yet_shipped_count > 0:
        action_id = new_id("ACT")
        cmd = {
            "action_id": action_id,
            "action_type": "inventory_hold",
            "description": f"Place inventory hold on {not_yet_shipped_count} suspect unit(s) of {part_number or 'affected part'} "
                            f"at Tier-1 Plant. {boundary_description}",
            "location": "Tier-1 Plant - Finished Goods",
            "quantity": not_yet_shipped_count,
            "status": "awaiting_approval",
        }
        _pending_actions[action_id] = cmd
        proposed_actions.append(cmd)

    if in_transit_count > 0:
        action_id = new_id("ACT")
        cmd = {
            "action_id": action_id,
            "action_type": "shipment_block",
            "description": f"Issue shipment-block / intercept instruction for {in_transit_count} suspect unit(s) "
                            f"currently in-transit to Northbridge. {boundary_description}",
            "location": "In-Transit",
            "quantity": in_transit_count,
            "status": "awaiting_approval",
        }
        _pending_actions[action_id] = cmd
        proposed_actions.append(cmd)

    if delivered_count > 0:
        action_id = new_id("ACT")
        cmd = {
            "action_id": action_id,
            "action_type": "100_percent_sort",
            "description": f"Request 100% sort/inspection and OEM notification for {delivered_count} suspect unit(s) "
                            f"already delivered to Northbridge/third-party warehouse. Do not contact dealers directly "
                            f"per containment procedure -- escalate through Northbridge Supplier Quality. {boundary_description}",
            "location": "Delivered (OEM / Third-Party Warehouse)",
            "quantity": delivered_count,
            "status": "awaiting_approval",
        }
        _pending_actions[action_id] = cmd
        proposed_actions.append(cmd)

    return {
        "part_number": part_number,
        "suspect_count_total": suspect_count,
        "affected_by_location": affected_by_location,
        "proposed_actions": proposed_actions,
    }


def execute_containment_action(payload: dict) -> dict:
    """Only marks a containment command executed after Coordinator relays human approval."""
    action_id = payload.get("action_id")
    approved = payload.get("approved", False)
    cmd = _pending_actions.get(action_id)
    if cmd is None:
        return {"error": f"Unknown action_id {action_id}"}
    if not approved:
        cmd["status"] = "rejected"
        return {"action_id": action_id, "status": "rejected", "detail": "Human approval was not granted."}
    cmd["status"] = "executed"
    return {"action_id": action_id, "status": "executed", "command": cmd}


def release_containment_action(payload: dict) -> dict:
    """
    Releases previously-contained material back to shippable/normal status.
    Only valid for a command that has actually reached 'executed' (i.e. was
    genuinely held) -- and, per the take-home's approval requirements,
    releasing contained material is itself an operational action that only
    proceeds after an explicit human approval flag from the Coordinator.
    """
    action_id = payload.get("action_id")
    approved = payload.get("approved", False)
    cmd = _pending_actions.get(action_id)
    if cmd is None:
        return {"error": f"Unknown action_id {action_id}"}
    if cmd["status"] != "executed":
        return {
            "error": f"Cannot release action_id {action_id}: current status is '{cmd['status']}', "
                     "expected 'executed' (material must actually be held before it can be released)."
        }
    if not approved:
        return {"action_id": action_id, "status": cmd["status"], "detail": "Release was not approved; the hold remains in effect."}
    cmd["status"] = "released"
    return {"action_id": action_id, "status": "released", "command": cmd}


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
    if message.action == "assess_containment":
        result = assess_containment(message.payload)
        status = ActionStatus.OK
        error = None
    elif message.action == "execute_containment_action":
        result = execute_containment_action(message.payload)
        status = ActionStatus.EXECUTED if result.get("status") == "executed" else ActionStatus.REJECTED
        error = result.get("error")
    elif message.action == "release_containment_action":
        result = release_containment_action(message.payload)
        status = ActionStatus.EXECUTED if result.get("status") == "released" else (
            ActionStatus.ERROR if result.get("error") else ActionStatus.REJECTED
        )
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

"""
Generates synthetic EPS-2200 manufacturing datasets with a deliberately
injected pattern: Line 2 / Evening shift / connector lot CON-771 shows a
disproportionate rate of Marginal/Fail EOL results, driven by a connector
press (Station 4B) force drifting out of the 45-65N control-plan spec after
a missed calibration -- this ties together the Traceability findings and the
Process/Maintenance findings into one coherent, defensible root-cause story
for the intermittent steering-warning-lamp symptom.

Run: python generate_data.py
Produces CSVs in this directory and loads them into manufacturing.db (SQLite).
"""
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

random.seed(42)

HERE = Path(__file__).parent
START = datetime(2025, 4, 20, 6, 0, 0)
END = datetime(2025, 5, 20, 22, 0, 0)

LINES = ["Line 1", "Line 2"]
SHIFTS = ["Day", "Evening"]
FIRMWARE = ["3.8.0", "3.8.1"]
PART_NUMBERS = ["EPS-2200-A", "EPS-2200-B"]

CONNECTOR_LOTS = ["CON-765", "CON-768", "CON-771", "CON-774", "CON-777"]
PCBA_LOTS = ["PCB-A190", "PCB-A191", "PCB-A192", "PCB-A193"]

OPERATORS = {
    ("Line 1", "Day"): ["OP-101", "OP-102"],
    ("Line 1", "Evening"): ["OP-103", "OP-104"],
    ("Line 2", "Day"): ["OP-201", "OP-202"],
    ("Line 2", "Evening"): ["OP-203", "OP-204"],
}
MACHINE_BY_LINE = {"Line 1": "PRESS-4A", "Line 2": "PRESS-4B"}

# --- Injected fault window: Line 2 / Evening / CON-771, press drift ---
FAULT_LINE = "Line 2"
FAULT_SHIFT = "Evening"
FAULT_LOT = "CON-771"
FAULT_WINDOW_START = datetime(2025, 5, 10, 14, 0, 0)
FAULT_WINDOW_END = datetime(2025, 5, 16, 22, 0, 0)


def gen_production_rows(n=260):
    rows = []
    serial_counter = 100000
    current = START
    step = (END - START) / n
    for i in range(n):
        ts = current + step * i + timedelta(minutes=random.randint(-20, 20))

        # Bias enough units into the injected fault segment (Line 2/Evening/CON-771)
        # while inside the fault window so the pattern is clearly visible in the
        # data, not left to chance -- the rest of the window still produces
        # normal-population units on other lines/shifts/lots for contrast.
        force_fault_segment = FAULT_WINDOW_START <= ts <= FAULT_WINDOW_END and random.random() < 0.45

        if force_fault_segment:
            line = FAULT_LINE
            shift = FAULT_SHIFT
            connector_lot = FAULT_LOT
        else:
            line = random.choice(LINES)
            shift = random.choice(SHIFTS)
            connector_lot = random.choice(CONNECTOR_LOTS)

        part_number = random.choices(PART_NUMBERS, weights=[0.7, 0.3])[0]
        firmware = random.choices(FIRMWARE, weights=[0.35, 0.65])[0]
        pcba_lot = random.choice(PCBA_LOTS)
        operator = random.choice(OPERATORS[(line, shift)])
        machine = MACHINE_BY_LINE[line]

        in_fault_window = (
            line == FAULT_LINE
            and shift == FAULT_SHIFT
            and connector_lot == FAULT_LOT
            and FAULT_WINDOW_START <= ts <= FAULT_WINDOW_END
        )

        # Nominal connector force ~ N(55, 3.5), clipped to plausible range.
        if in_fault_window:
            # Drifted low, out of the 45-65N spec band on many (not all) units.
            force = round(random.gauss(41.5, 4.0), 1)
        else:
            force = round(random.gauss(55.0, 3.5), 1)
        force = max(20.0, min(75.0, force))

        # Contact resistance correlates inversely with insertion force.
        base_resistance = max(5.0, 140 - (force * 1.9) + random.gauss(0, 6))
        contact_resistance_mohm = round(max(3.0, base_resistance), 1)

        if contact_resistance_mohm < 50:
            eol_result = "Pass"
        elif contact_resistance_mohm <= 100:
            eol_result = "Marginal"
        else:
            eol_result = "Fail"

        # Small independent chance of Marginal/Fail unrelated to the fault window (background noise).
        if not in_fault_window and random.random() < 0.03:
            eol_result = random.choice(["Marginal", "Fail"])

        serial_counter += 1
        rows.append(
            {
                "serial_number": f"SN-EPS{serial_counter}",
                "part_number": part_number,
                "production_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "line": line,
                "shift": shift,
                "operator_id": operator,
                "machine_id": machine,
                "connector_force_n": force,
                "contact_resistance_mohm": contact_resistance_mohm,
                "eol_result": eol_result,
                "firmware_version": firmware,
                "connector_lot": connector_lot,
                "pcba_lot": pcba_lot,
            }
        )
    rows.sort(key=lambda r: r["production_time"])
    return rows


def gen_alarms(production_df: pd.DataFrame):
    rows = []
    # Force-out-of-spec alarms cluster in the fault window on PRESS-4B.
    fault_rows = production_df[
        (production_df.line == FAULT_LINE)
        & (production_df['shift'] == FAULT_SHIFT)
        & (production_df.connector_lot == FAULT_LOT)
        & (production_df.connector_force_n < 45)
    ]
    for _, r in fault_rows.iterrows():
        rows.append(
            {
                "alarm_time": r.production_time,
                "machine_id": r.machine_id,
                "line": r.line,
                "alarm_code": "FORCE_LOW_4B",
                "description": "Connector insertion force below 45N lower control limit",
                "value": r.connector_force_n,
            }
        )
    # A few background/unrelated alarms for realism.
    for _ in range(8):
        t = START + timedelta(days=random.randint(0, 29), hours=random.randint(6, 21))
        rows.append(
            {
                "alarm_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                "machine_id": random.choice(["PRESS-4A", "PRESS-4B", "FLASH-STN-1", "EOL-TESTER-1"]),
                "line": random.choice(LINES),
                "alarm_code": random.choice(["E-STOP", "SENSOR_COMM_RETRY", "AIR_PRESSURE_LOW"]),
                "description": "Routine transient alarm, auto-cleared",
                "value": None,
            }
        )
    rows.sort(key=lambda r: r["alarm_time"])
    return rows


def gen_calibration():
    rows = []
    machines = ["PRESS-4A", "PRESS-4B", "TORQUE-CAL-FIXTURE-1"]
    d = START
    while d <= END:
        for m in machines:
            # PRESS-4B misses its scheduled calibration window right before the fault window.
            if m == "PRESS-4B" and datetime(2025, 5, 8) <= d <= datetime(2025, 5, 10):
                continue
            if d.day % 7 == (0 if m != "TORQUE-CAL-FIXTURE-1" else 1):
                status = "Pass"
                if m == "PRESS-4B" and d >= datetime(2025, 5, 10):
                    status = "Fail - Recalibrated"
                rows.append(
                    {
                        "calibration_date": d.strftime("%Y-%m-%d"),
                        "machine_id": m,
                        "calibration_type": "Force Cell" if "PRESS" in m else "Torque Reference",
                        "result": status,
                        "next_due": (d + timedelta(days=30)).strftime("%Y-%m-%d"),
                    }
                )
        d += timedelta(days=1)
    return rows


def gen_maintenance():
    rows = [
        {
            "date": "2025-05-16",
            "machine_id": "PRESS-4B",
            "line": "Line 2",
            "work_type": "Corrective",
            "description": (
                "Investigated repeated FORCE_LOW_4B alarms on Evening shift. Found "
                "press force-cell calibration had drifted low following a missed "
                "30-day calibration cycle (due 2025-05-09, not performed until "
                "2025-05-16). Recalibrated force cell and replaced worn insertion "
                "tooling. Verified force output within 45-65N spec post-repair."
            ),
            "technician_id": "MAINT-07",
        },
        {
            "date": "2025-05-09",
            "machine_id": "PRESS-4B",
            "line": "Line 2",
            "work_type": "Preventive (Missed)",
            "description": (
                "Scheduled 30-day force-cell calibration for PRESS-4B was not "
                "completed as planned due to technician availability; rescheduled."
            ),
            "technician_id": "MAINT-03",
        },
        {
            "date": "2025-04-22",
            "machine_id": "PRESS-4A",
            "line": "Line 1",
            "work_type": "Preventive",
            "description": "Routine 30-day force-cell calibration and tooling inspection. Within spec.",
            "technician_id": "MAINT-03",
        },
        {
            "date": "2025-05-02",
            "machine_id": "EOL-TESTER-1",
            "line": "Both",
            "work_type": "Preventive",
            "description": "Routine EOL tester reference-standard verification. Within spec.",
            "technician_id": "MAINT-05",
        },
        {
            "date": "2025-04-28",
            "machine_id": "FLASH-STN-1",
            "line": "Both",
            "work_type": "Corrective",
            "description": "Updated flash station firmware image repository to remove superseded 3.7.9 image per AFL update; confirmed only 3.8.0/3.8.1 available for flashing.",
            "technician_id": "MAINT-09",
        },
    ]
    return rows


def gen_inventory():
    locations = [
        ("Tier-1 Plant - Finished Goods", "plant"),
        ("In-Transit to Northbridge Assembly Plant", "in_transit"),
        ("Third-Party Warehouse - Midwest DC", "third_party_warehouse"),
        ("Northbridge OEM Receiving Dock", "oem"),
    ]
    rows = []
    for loc_name, loc_type in locations:
        for pn in PART_NUMBERS:
            rows.append(
                {
                    "location_name": loc_name,
                    "location_type": loc_type,
                    "part_number": pn,
                    "quantity_on_hand": random.randint(150, 900),
                }
            )
    return rows


def gen_shipments(production_df: pd.DataFrame):
    rows = []
    shipped = production_df.sample(frac=0.55, random_state=42)
    vin_counter = 700000
    for _, r in shipped.iterrows():
        vin_counter += 1
        ship_date = (datetime.strptime(r.production_time, "%Y-%m-%d %H:%M:%S") + timedelta(days=random.randint(1, 5)))
        destination = random.choices(
            ["Northbridge Assembly Plant - Riverbend", "Northbridge Assembly Plant - Danforth", "Third-Party Warehouse - Midwest DC"],
            weights=[0.5, 0.3, 0.2],
        )[0]
        rows.append(
            {
                "serial_number": r.serial_number,
                "part_number": r.part_number,
                "ship_date": ship_date.strftime("%Y-%m-%d"),
                "destination": destination,
                "vin": f"1NB{vin_counter}EPS2025",
                "status": "Delivered" if ship_date < datetime(2025, 5, 18) else "In-Transit",
            }
        )
    return rows


def main():
    production_rows = gen_production_rows()
    production_df = pd.DataFrame(production_rows)
    production_df.to_csv(HERE / "production.csv", index=False)

    alarms_df = pd.DataFrame(gen_alarms(production_df))
    alarms_df.to_csv(HERE / "alarms.csv", index=False)

    calibration_df = pd.DataFrame(gen_calibration())
    calibration_df.to_csv(HERE / "calibration.csv", index=False)

    maintenance_df = pd.DataFrame(gen_maintenance())
    maintenance_df.to_csv(HERE / "maintenance.csv", index=False)

    inventory_df = pd.DataFrame(gen_inventory())
    inventory_df.to_csv(HERE / "inventory.csv", index=False)

    shipments_df = pd.DataFrame(gen_shipments(production_df))
    shipments_df.to_csv(HERE / "shipments.csv", index=False)

    db_path = HERE / "manufacturing.db"
    conn = sqlite3.connect(db_path)
    production_df.to_sql("production", conn, if_exists="replace", index=False)
    alarms_df.to_sql("alarms", conn, if_exists="replace", index=False)
    calibration_df.to_sql("calibration", conn, if_exists="replace", index=False)
    maintenance_df.to_sql("maintenance", conn, if_exists="replace", index=False)
    inventory_df.to_sql("inventory", conn, if_exists="replace", index=False)
    shipments_df.to_sql("shipments", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    print(f"Generated {len(production_df)} production rows, {len(alarms_df)} alarms, "
          f"{len(calibration_df)} calibration records, {len(maintenance_df)} maintenance "
          f"records, {len(inventory_df)} inventory rows, {len(shipments_df)} shipment rows.")
    print(f"SQLite DB written to {db_path}")
    fault_pop = production_df[
        (production_df.line == FAULT_LINE)
        & (production_df['shift'] == FAULT_SHIFT)
        & (production_df.connector_lot == FAULT_LOT)
    ]
    print(f"Injected fault segment (Line 2/Evening/CON-771) size: {len(fault_pop)}, "
          f"Marginal/Fail rate: {(fault_pop.eol_result != 'Pass').mean():.1%}")
    overall_bad_rate = (production_df.eol_result != "Pass").mean()
    print(f"Overall Marginal/Fail rate: {overall_bad_rate:.1%}")


if __name__ == "__main__":
    main()

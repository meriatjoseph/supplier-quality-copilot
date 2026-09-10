# EPS-2200 Control Plan
Document No: CP-EPS-2200 Rev. F
Process: EPS Control Module Assembly, Lines 1 & 2

## Section 1: Process Flow Overview
1. PCBA kitting and ECU housing sub-assembly
2. Torque sensor installation and calibration
3. Wiring harness connector insertion (automatic press, Stations 4A/4B)
4. Firmware flash and configuration
5. End-of-line (EOL) electrical/functional test
6. Final visual inspection and pack-out

## Section 2: Connector Insertion Force — Control Characteristic
Special Characteristic: YES (Safety-related, linked to steering signal
continuity)
Machine: Automatic connector press, Stations 4A (Line 1) / 4B (Line 2)
Specification: Insertion/seating force 45 N – 65 N, measured by in-line load
cell on every unit.
Control Method: 100% automated force monitoring with SPC charting per shift.
Reaction Plan: Any reading outside 45-65 N triggers automatic machine stop
and requires connector re-seat and re-test; three consecutive out-of-spec
readings requires press recalibration by Maintenance before resuming
production. Press calibration is required at minimum every 30 days per
PM-EPS-PRESS-01.
Rationale: Under-force insertion can result in an intermittent electrical
connection at the harness-to-ECU interface that may not be detected at EOL
under bench conditions but can manifest intermittently in vehicle-level
thermal/vibration conditions as an intermittent steering warning lamp event.

## Section 3: Torque Sensor Calibration — Control Characteristic
Special Characteristic: YES
Specification: Sensor output must be within +/-1.5% of reference torque
across calibration range; calibration verified daily at shift start using a
certified reference fixture.
Reaction Plan: Calibration drift beyond +/-1.5% requires immediate line stop,
sensor swap, and quarantine of all units produced since the last passing
calibration check.

## Section 4: Firmware Flash and Configuration — Control Characteristic
Special Characteristic: YES (Safety-related, fault-code and warning-lamp
logic)
Specification: Only firmware versions on the Approved Firmware List (AFL) may
be flashed. Current AFL for EPS-2200: 3.8.0, 3.8.1 (production released).
Version 3.7.9 was superseded and removed from the AFL after Northbridge
concurrence; version 3.9.0 is in engineering validation and is NOT yet
released for production intent.
Reaction Plan: Any unit flashed with a non-AFL firmware version must be
quarantined and re-flashed prior to EOL test.

## Section 5: End-of-Line (EOL) Electrical Test — Control Characteristic
Special Characteristic: YES
Specification: Steering angle sensor signal, torque sensor signal, CAN
communication, warning-lamp driver circuit, and connector continuity/contact
resistance must all pass per NBM-EOL-EPS-2024. Contact resistance at the
harness connector must read below 50 milliohms; 50-100 milliohms is scored
"Marginal" and re-tested once; above 100 milliohms or any open circuit is
"Fail."
Reaction Plan: See EOL procedure (Document 04) for disposition of Marginal
and Fail results.

## Section 6: Environmental Stress Notes
Connector interfaces marginally within spec at room-temperature EOL test have
been observed in prior programs to be more susceptible to intermittent
opens under thermal cycling and vibration once in vehicle service -- this is
why contact resistance, not just a pass/fail continuity check, is monitored
at EOL for this program.

# End-of-Line (EOL) Electrical Test Procedure
Document No: NBM-EOL-EPS-2024 Rev. B
Applies to: EPS-2200-A, EPS-2200-B

## Section 1: Purpose
Defines the 100% end-of-line electrical/functional test performed on every
EPS control module prior to release from the plant, and the disposition
rules for non-passing results.

## Section 2: Test Sequence
1. Power-on self-test and CAN bus enumeration
2. Steering angle sensor signal verification (full range sweep)
3. Torque sensor signal verification against reference load
4. Warning-lamp driver circuit continuity and function check
5. Harness connector contact resistance measurement
6. Firmware version read-back and comparison to work order
7. Final PASS / MARGINAL / FAIL determination and label print

## Section 3: Acceptance Criteria
- Contact resistance < 50 milliohms: PASS
- Contact resistance 50-100 milliohms: MARGINAL
- Contact resistance > 100 milliohms or open circuit: FAIL
- Any sensor signal outside calibrated range: FAIL
- Firmware version not matching work order or not on Approved Firmware List:
  FAIL
- CAN bus enumeration failure: FAIL

## Section 4: Disposition Rules
MARGINAL: Re-test once after connector re-seat. If second result is PASS,
unit may ship. If second result is MARGINAL or FAIL, unit is quarantined.
FAIL: Unit is quarantined immediately; no re-test without engineering
disposition (rework, scrap, or use-as-is with Northbridge concurrence).
A unit may not be re-tested more than twice without a quarantine tag and
documented root cause of the initial failure.

## Section 5: Data Retention
EOL test results (raw measurement values, not just PASS/FAIL) must be
retained and linked to serial number for a minimum of 7 years, to support
traceability requests per the Customer-Specific Requirements (Document 01,
Section 3) and containment investigations per the Traceability and
Containment Procedure (Document 05).

## Section 6: Known Limitation — Room-Temperature Test Conditions
EOL testing is performed at ambient plant temperature (approximately 20-24C)
and without vibration simulation. Connector interfaces that measure as
PASS or low-MARGINAL contact resistance at room temperature have, in prior
programs, occasionally still exhibited intermittent opens once exposed to
underhood thermal cycling and road vibration in vehicle service. This is a
known gap between EOL test conditions and field use conditions for
borderline connector seating, and should be considered when investigating
field complaints that were not caught by EOL.

# EPS-2200 Process FMEA (PFMEA)
Document No: PFMEA-EPS-2200 Rev. D

## Section 1: Process Step — Connector Insertion (Station 4A/4B)
Potential Failure Mode: Under-seated / low-force connector insertion
Potential Effect: Intermittent electrical open at harness-to-ECU connector;
at vehicle level this can present as an intermittent steering warning lamp
illumination and/or momentary loss of torque assist signal, particularly
under vibration or thermal cycling.
Severity: 9 (safety-related, per Northbridge CSR Class A classification)
Potential Cause: Connector press force out of calibration; worn press
tooling; component lot dimensional variation in connector housing from
supplier lot; operator bypass of press cycle.
Current Controls (Prevention): Press force spec 45-65N with automated
monitoring; incoming inspection sampling of connector lots.
Current Controls (Detection): 100% in-line force monitoring at insertion;
EOL contact-resistance test.
Occurrence: 4  Detection: 5  RPN: 180 (highest RPN process step on this line)
Recommended Action: Tighten SPC reaction limits, add lot-level incoming
dimensional check for connector housings, evaluate EOL contact-resistance
threshold sensitivity to catch marginal seating that passes EOL at room
temperature but is susceptible to thermal/vibration-induced intermittent
opens in service.

## Section 2: Process Step — Firmware Flash
Potential Failure Mode: Incorrect or non-AFL firmware version flashed
Potential Effect: Incorrect fault-code thresholds or warning-lamp logic;
can cause false/nuisance steering warning lamp illumination even when the
underlying sensor and electrical signal are within normal operating range.
Severity: 8
Potential Cause: Flash station configuration error; use of superseded
firmware version 3.7.9 remaining on a flash station image after AFL update.
Current Controls (Prevention): Flash station pulls firmware from
version-controlled AFL repository.
Current Controls (Detection): EOL functional test verifies firmware version
against work order.
Occurrence: 2  Detection: 3  RPN: 48

## Section 3: Process Step — Torque Sensor Calibration
Potential Failure Mode: Sensor calibration drift
Potential Effect: Incorrect torque assist output; potential steering feel
complaint; in severe drift, fault code triggering steering warning lamp.
Severity: 8
Potential Cause: Reference fixture wear; missed daily calibration check.
Current Controls (Prevention): Daily calibration verification at shift
start.
Current Controls (Detection): EOL torque signal test.
Occurrence: 2  Detection: 4  RPN: 64

## Section 4: Process Step — EOL Electrical Test
Potential Failure Mode: Marginal result accepted without proper disposition
Potential Effect: Unit with borderline connector contact resistance ships
and later fails intermittently in the field.
Severity: 9
Potential Cause: Operator override of Marginal disposition; unclear
work instruction on re-test handling.
Current Controls (Prevention): EOL procedure requires quarantine on second
Marginal result.
Current Controls (Detection): None beyond EOL itself -- this is an end-of-line
control, not an upstream prevention.
Occurrence: 3  Detection: 6  RPN: 162

## Section 5: Recommended Priority
Based on RPN ranking, Connector Insertion (RPN 180) and EOL Marginal
Disposition (RPN 162) are the highest-priority failure modes for the
intermittent steering-warning-lamp symptom family and should be the first
areas investigated when this symptom is reported by the OEM.

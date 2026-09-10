# 8D Report (Historical Reference) — OEM-INC-2023-041
Document No: 8D-2023-041 Rev. Final (Closed)
Part: EPS-2200-A
Symptom: Intermittent steering warning lamp illumination, no stored DTC
correlating to an actual sensor fault.

## D1: Team
Supplier Quality Engineer, Firmware Engineering Lead, Process Engineer,
Northbridge SQE (customer representative).

## D2: Problem Description
Northbridge field reports (11 vehicles, 2023-08 through 2023-09) of
intermittent steering warning lamp illumination with no repeatable fault
found at dealer diagnostic scan. No connector or wiring damage found on
returned units.

## D3: Interim Containment
Inventory hold placed on all units produced with firmware 3.7.9 (a
transitional version used during flash-station image update). Shipment hold
extended to in-transit stock. No sort action was needed since the issue was
firmware logic, not a hardware/assembly defect.

## D4: Root Cause
Firmware version 3.7.9 contained a fault-code debounce timing defect: a
transient CAN bus signal delay (within normal tolerance) under certain
combinations of ambient temperature and battery voltage was incorrectly
latched as a steering angle sensor fault, illuminating the warning lamp for
several seconds before self-clearing. This was a logic defect, not a
hardware or connector defect -- returned units showed no electrical or
mechanical abnormality.

## D5/D6: Corrective Action
Firmware 3.7.9 was removed from the Approved Firmware List (AFL) and
superseded by 3.8.0, which corrected the debounce timing logic. All
in-process and held inventory was re-flashed to 3.8.0 prior to release.
Flash station images were audited to confirm no station retained 3.7.9.

## D7: Effectiveness Verification
No recurrence of the debounce-related warning lamp complaint in the 90 days
following corrective action implementation. Firmware versions 3.8.0 and
3.8.1 (a later minor update, unrelated to this defect) remain on the current
Approved Firmware List.

## Lessons Learned
Intermittent steering-warning-lamp symptoms with no correlating stored DTC
or hardware damage should include firmware/logic review as a parallel
investigation track alongside hardware/assembly causes, since this failure
mode has a precedent in firmware logic rather than a physical defect. Note,
however, that returned units in this prior case showed no connector or
contact-resistance abnormality -- a current investigation should confirm
whether connector/contact-resistance findings are present before assuming
this is a repeat of the same firmware-logic root cause.

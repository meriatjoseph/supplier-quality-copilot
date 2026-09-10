# Northbridge Motors — Customer-Specific Requirements (CSR)
Document No: NBM-CSR-EPS-2024 Rev. C
Applies to: Electronic Power Steering (EPS) Control Modules, Part Family EPS-2200

## Section 1: Scope and Applicability
This CSR supplements IATF 16949 and applies to all Tier-1 suppliers producing
Electronic Power Steering (EPS) control modules for Northbridge Motors vehicle
programs. It governs quality planning, production part approval, in-process
control, containment, and corrective action expectations for the EPS-2200
module family, including part numbers EPS-2200-A and EPS-2200-B.

## Section 2: Zero-Defect Expectation for Safety-Critical Systems
EPS control modules are classified as Safety-Critical (Class A) components per
Northbridge's Design Failure Mode severity ranking, because a loss of assist or
false steering warning indication can affect vehicle controllability. Suppliers
must maintain a rolling 12-month field PPM target of less than 5 PPM for
safety-related complaints. Any warranty return coded "Steering Warning Lamp
Illumination" or "Intermittent Loss of Assist" must trigger an accelerated
8D response per Section 4.

## Section 3: Traceability Requirements
Suppliers must maintain full genealogy for every EPS module shipped, including:
serial number, production date/time, production line and shift, connector
crimp/insertion force reading, end-of-line (EOL) electrical test result,
installed firmware version, and component lot numbers for all safety-critical
purchased components (connector assemblies, torque sensor, ECU PCBA). This
genealogy must be retrievable within 4 business hours of an OEM request and
must support bidirectional traceability from vehicle VIN to component lot.

## Section 4: 8D / Corrective Action Timing
Upon receipt of a formal quality complaint (OEM-INC), the supplier must:
- Acknowledge receipt within 24 hours.
- Submit interim containment actions (D1-D3) within 3 calendar days.
- Submit root cause and permanent corrective action plan (D4-D6) within 15
  calendar days for Class A safety complaints, 30 calendar days otherwise.
- Provide effectiveness verification (D7) within 60 days of implementation.

## Section 5: Containment and Sort Requirements
When a suspect population is identified, the supplier must, at minimum:
1. Place an inventory hold on all suspect serial numbers/lots at the Tier-1
   plant and any downstream Tier-1-controlled warehouse.
2. Notify Northbridge Supplier Quality within 24 hours with the suspect
   population size, boundary logic (line/shift/lot/date range), and proposed
   containment action.
3. Perform 100% sort/inspection of suspect stock not yet shipped, using an
   approved inspection method tied to the suspected failure mode.
4. Where product has already shipped, coordinate with Northbridge Logistics on
   in-transit and dealer-network hold instructions; do NOT contact dealers or
   end customers directly without Northbridge Supplier Quality sign-off.

## Section 6: EOL Electrical Test Acceptance
Every EPS-2200 module must pass 100% end-of-line electrical test per
NBM-EOL-EPS-2024 prior to release. Any "Marginal" result must be re-tested
once; a second Marginal or any "Fail" result routes the unit to quarantine and
requires disposition (scrap, rework, or engineering use-as-is with Northbridge
concurrence) before it may re-enter the shippable population.

## Section 7: Firmware Configuration Control
Firmware revisions for the steering angle/torque control algorithm must be
under configuration control. A firmware change affecting steering warning
lamp logic or fault-code thresholds requires Northbridge Engineering
notification and, for safety-related logic, a Production Part Approval
Process (PPAP) Level 3 resubmission before it may be used in production
intent for shipment to Northbridge.

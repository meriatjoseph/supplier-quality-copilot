# Product Traceability and Containment Procedure
Document No: SQP-TRACE-014 Rev. E

## Section 1: Purpose and Scope
Defines how genealogy data is used to identify a suspect population in
response to a quality complaint, and the required containment sequence once
a suspect population is identified. Applies to all safety-classified part
families, including EPS-2200.

## Section 2: Traceability Data Elements
For every EPS-2200 serial number, the following genealogy must be linkable:
production line, shift, production timestamp, connector insertion force
reading, torque sensor calibration status, EOL test result (including
Marginal/Fail history), firmware version installed, component lot numbers
(connector assembly lot, ECU PCBA lot), operator ID, and machine ID.

## Section 3: Suspect Population Identification Method
When an OEM complaint is received:
1. Establish the affected date range from the complaint (production date
   range, or estimated production date range back-calculated from
   vehicle build date if only VIN/build date is provided).
2. Query all serial numbers produced in that window.
3. Segment by line, shift, firmware version, and component lot.
4. Compare the EOL Marginal/Fail rate and any downstream field-return rate
   across segments to identify whether any segment shows a disproportionate
   concentration of the symptom relative to the overall population.
5. The recommended containment boundary should be the narrowest segment
   that captures the disproportionate concentration -- avoid over-scoping
   (unnecessarily holding good product) or under-scoping (missing suspect
   product) the containment population.

## Section 4: Containment Sequence
Once a suspect population and boundary are identified:
1. Place immediate inventory hold at the Tier-1 plant for all suspect
   serials/lots still on site.
2. Determine in-transit and downstream (third-party warehouse, OEM-side)
   inventory quantities within the suspect boundary and issue shipment-block
   instructions for any not yet delivered to the OEM production line.
3. For product already at the OEM or in vehicles, escalate to Northbridge
   Supplier Quality for joint disposition -- do not unilaterally contact
   dealers or end customers.
4. Initiate 100% sort/inspection of held suspect stock using a method
   appropriate to the suspected failure mode (e.g., contact-resistance
   re-test for a connector-force-related suspect population).
5. Document the containment boundary and rationale in the 8D (D3) and update
   as the investigation narrows or widens the suspect population.

## Section 5: Boundary Revision
The suspect population boundary is a working hypothesis, not a final
determination. As root cause investigation proceeds (see PFMEA, Document 03,
and process/maintenance data), the boundary should be revised -- and
containment scope adjusted accordingly -- rather than treated as fixed once
set in D3.

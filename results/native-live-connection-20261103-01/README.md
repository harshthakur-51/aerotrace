# Native live connection acceptance - 3 November 2026

Source commit: `e0430bb`. An owned local FlightGear/A320 process was launched using
the existing takeoff-state ground configuration. Read-only startup checks observed
initialization complete, both engines running, ground contact, pause clear and both
selected native fault flags clear. Runtime version read back as FlightGear 2024.1.7.
The existing collector/model pin is configuration provenance, not an independent
validation of aircraft behavior. The process was stopped after this check.

The same `PanelState` and HTTP panel used by the product collected 32 complete public
polls with advancing simulator time. All twelve selected channels were retained.
The final live result and evidence exactly equaled offline diagnosis on those same
saved observations. The final compatible configuration was `selected_reference`,
meaning no selected anomaly in the explained window, not whole-aircraft health.
Maximum observed poll span was 0.316160 seconds and diagnosis update 0.004301 seconds.
This is a short connection acceptance run, not a real-time guarantee, independent
accuracy trial or validation of long-session performance.

No fault/aircraft-control writes occurred. The two fault flags remained clear at
final readback. Private readiness checks and source/setup provenance stay under
`private_truth`; only `observations.jsonl` enters offline inference. Startup waiting
precedes the recorded window and is not presented as complete public coverage.
The helper and executed sources are archived. Existing aircraft-response recordings
and software checks remain unchanged.

The browser inspector showed the final no-selected-anomaly result. Collection had
already ended, so the captured screenshot correctly marks the retained snapshot as
STALE and disables fault controls. It is not a screenshot of fresh live telemetry.
No console errors were observed. The temporary acceptance server was closed; the
separate recorded review panel on port 8766 remains the morning demo.

**Limit:** this is an on-ground connection acceptance run. It does not establish
live airborne fault response or real-aircraft validity. No fault was injected.
The recording is development/integration evidence, not a newly locked final test.

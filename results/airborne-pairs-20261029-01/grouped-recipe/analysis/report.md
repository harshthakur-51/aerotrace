# Airborne-profile observation replay

Selected-system assessment: **no_fault_observed**.

This report retains flight context; it does not establish airborne qualification, physical fault validation or whole-aircraft controllability.

Profile: `a320-stable-airborne-v1`; samples: 80.
Context indications: airborne_indications_observed. All twenty channels currently usable: True.

## Latest flight context and automation

| Channel | Value | Unit | Current quality |
|---|---|---|---|
| aircraft | A320-200-CFM |  | observed |
| sim_time | 346.516667 | s | observed |
| paused | False |  | observed |
| altitude | 10171.519225 | ft | observed |
| airspeed | 250.317957 | kt | observed |
| main_gear_1_wow | False |  | observed |
| main_gear_2_wow | False |  | observed |
| height_agl | 10173.629473 | ft | observed |
| vertical_speed | -0.046556 | ft/s | observed |
| bank | -0.054132 | deg | observed |
| autopilot_1 | True |  | observed |
| autopilot_2 | False |  | observed |
| autothrust | True |  | observed |

## Compatible explanations

- no selected anomaly currently observed (compatible): The selected channels are currently near their references. This is not a whole-aircraft health claim.

## Observed impact

No selected confirmed impact; this does not establish health.

## Evidence and context history

- E0001 generator_2_source_unavailable: first observed at 285.991667 simulator seconds, confirmed at 286.991667 simulator seconds.
- E0002 blue_inventory_loss: first observed at 287.041667 simulator seconds, confirmed at 288.033333 simulator seconds.
- E0003 generator_output_restored: first observed at 338.566667 simulator seconds, confirmed at 338.566667 simulator seconds.
- E0004 blue_quantity_returned_to_reference: first observed at 338.608333 simulator seconds, confirmed at 338.608333 simulator seconds.
- 756 observed value/quality changes; all twenty-channel snapshots and changes are retained in report.json.

## Limits and provenance

- Thresholds are illustrative native-model detector choices; provenance: aircraft_debugger/evidence.py. They are not physical laws or aircraft warning limits.
- A stable or energized observed reference does not establish that the whole aircraft is healthy.
- Internal simulator properties have not been validated as realistic aircraft sensors.
- Readings are non-atomic. Simulator seconds and local monotonic seconds are distinct clocks and are never subtracted from each other.
- Current means the final recorded sample, not a live assessment at the wall-clock time when this historical file is replayed.
- Event onset means the first observed qualifying change, not the exact physical failure time; confirmation can occur later.
- Closely timed electrical and hydraulic observations do not identify a shared initiating cause. Independent faults remain equally compatible.
- The two multi-system explanations are a limited comparison, not an exhaustive set of causes. No evidence here establishes fire or an uncontained engine failure.
- Retained bus voltage or hydraulic pressure does not establish full remaining capability, flightworthiness, or safe flight.
- Upward hydraulic quantity changes can reflect the native model's automatic restoration. They do not prove repair or physical fluid recovery.
- This report analyzes the airborne observation profile; it does not certify that a flight was qualified or that a physical fault experiment was performed.
- Selected voltage/inventory compatibility rules are reused from aircraft_debugger.evidence. Their thresholds are project choices, not aircraft warning limits or calibrated probabilities.
- All twenty recorded channels, transport quality and per-reading timestamps remain in retained_observations. Derived current values are null when unavailable; raw historical values are not substituted for current evidence.
- No stability-band or admission filter is applied. Motion after any event remains an observation, including altitude, airspeed and bank departures.
- Automation engagement is observed context. Unchanged motion with engaged automation, retained pressure or a normal bus does not establish healthy actuators or whole-aircraft controllability.
- Observed contact/height indications do not independently establish loaded-terrain validity, flightworthiness or an admitted airborne baseline.
- Context changes are observations, not proof that a fault caused the motion. Simulator time and local monotonic time are separate clocks.
- Current means the final recorded sample; replay does not establish live state at the wall-clock time of analysis.
- Canonical observation SHA-256: `ca81164ec38bef5a8dbe99d3d10071d940468bcb07e00be0045a522ef40b931c`.
- Original observation-file SHA-256: `cdb8e4f58eea8a6ab96521f0fee9e45ae38700ee1cfd84efe11e00dcea1ac045`.

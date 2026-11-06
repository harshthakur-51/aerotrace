# Observation-only evidence replay

Assessment: **isolated_electrical_anomaly**

Compatibility rules only. No cause probabilities or flightworthiness verdict.

## Current observations

- generator_2: source_unavailable
- ac_bus_2: supply_retained
- blue_inventory: near_observed_reference
- blue_pressure: pressure_retained

## Possible explanations

- electrical supply/source anomaly (compatible): Output or bus voltage is abnormal relative to the detector choices. Engine stoppage, switching, supply configuration and component faults are not distinguished.

## Observed impact

- Generator 2 source output unavailable; one observed source is lost. AC bus 2 voltage remains available; total bus loss is not observed.

## Evidence ledger

- E0001 generator_2_source_unavailable: first observed at simulator 187.816667 s; confirmed at 188.825 s. Low output persisted on two advancing readings after an observed energized reference; this is source-output evidence, not identification of a generator fault.

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

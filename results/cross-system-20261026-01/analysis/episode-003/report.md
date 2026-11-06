# Observation-only evidence replay

Assessment: **hydraulic_depletion**

Compatibility rules only. No cause probabilities or flightworthiness verdict.

## Current observations

- generator_2: energized_output_observed
- ac_bus_2: supply_retained
- blue_inventory: inventory_loss_observed
- blue_pressure: pressure_retained

## Possible explanations

- hydraulic inventory depletion (compatible): Observed quantity decreased from its reference; external leakage is one possible explanation, not a uniquely identified cause.

## Observed impact

- Blue-system inventory loss observed. Pressure remains in the illustrative retained range; inventory loss can precede pressure degradation.

## Evidence ledger

- E0001 blue_inventory_loss: first observed at simulator 204.941667 s; confirmed at 205.966667 s. Observed quantity fell at least 0.5 raw model units from its reference across advancing readings. This does not identify a leak or its initiating cause.

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

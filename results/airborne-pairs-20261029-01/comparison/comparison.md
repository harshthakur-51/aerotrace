# Public-input paired observation comparison

Both public inputs contain multiple-system prefixes with equally compatible explanations and no identified initiating cause.

InputA/inputB are public-input identifiers. No private initiating-cause label is used.

## inputA

Public samples: 80.
Final selected category: `no_fault_observed`.
Multiple-system category observed at 51 public prefixes.

| Category transition index | Observed simulator time (s) | Category |
|---|---|---|
| 0 | 268.308333 | insufficient_current_evidence |
| 1 | 269.3 | no_fault_observed |
| 18 | 285.933333 | insufficient_current_evidence |
| 19 | 286.925 | isolated_electrical_anomaly |
| 20 | 287.925 | multiple_system_anomalies |
| 71 | 338.5 | hydraulic_pressure_anomaly |
| 76 | 343.516667 | no_fault_observed |

Candidate-set variants during multiple-system prefixes:

- independent electrical/hydraulic faults (equally_compatible); shared regional damage (equally_compatible)

All multiple-system candidates equally compatible: True.
Cause unidentified at every multiple-system prefix: True.

All-input selected ranges (including baseline and recovery if present):

| Public channel | Minimum | Maximum | Unit | Unavailable samples |
|---|---|---|---|---|
| generator_2_voltage | 0.0 | 115.000888 | V | 0 |
| ac_bus_1 | 114.998922 | 115.000888 | V | 0 |
| ac_bus_2 | 114.998922 | 115.000888 | V | 0 |
| blue_quantity | 0.0 | 8.0 | raw model quantity | 0 |
| blue_pressure | 0.0 | 3000.0 | psi | 0 |
| altitude | 10171.026796 | 10171.550003 | ft | 0 |
| airspeed | 250.313434 | 250.325408 | kt | 0 |
| height_agl | 9991.448021 | 10183.206914 | ft | 0 |
| vertical_speed | -0.064379 | 0.049553 | ft/s | 0 |
| bank | -0.054173 | -0.054098 | deg | 0 |

Recorded automation/contact value counts:

- main_gear_1_wow: {'false': 80}; unavailable: 0.
- main_gear_2_wow: {'false': 80}; unavailable: 0.
- autopilot_1: {'true': 80}; unavailable: 0.
- autopilot_2: {'false': 80}; unavailable: 0.
- autothrust: {'true': 80}; unavailable: 0.

Observation-file SHA-256: `cdb8e4f58eea8a6ab96521f0fee9e45ae38700ee1cfd84efe11e00dcea1ac045`.

## inputB

Public samples: 81.
Final selected category: `no_fault_observed`.
Multiple-system category observed at 51 public prefixes.

| Category transition index | Observed simulator time (s) | Category |
|---|---|---|
| 0 | 371.325 | insufficient_current_evidence |
| 1 | 372.308333 | no_fault_observed |
| 18 | 388.875 | insufficient_current_evidence |
| 19 | 389.883333 | isolated_electrical_anomaly |
| 20 | 390.883333 | multiple_system_anomalies |
| 71 | 441.45 | hydraulic_pressure_anomaly |
| 76 | 446.475 | no_fault_observed |

Candidate-set variants during multiple-system prefixes:

- independent electrical/hydraulic faults (equally_compatible); shared regional damage (equally_compatible)

All multiple-system candidates equally compatible: True.
Cause unidentified at every multiple-system prefix: True.

All-input selected ranges (including baseline and recovery if present):

| Public channel | Minimum | Maximum | Unit | Unavailable samples |
|---|---|---|---|---|
| generator_2_voltage | 0.0 | 115.000723 | V | 0 |
| ac_bus_1 | 115.000859 | 115.000859 | V | 0 |
| ac_bus_2 | 115.000859 | 115.000859 | V | 0 |
| blue_quantity | 0.0 | 8.0 | raw model quantity | 0 |
| blue_pressure | 0.0 | 3000.0 | psi | 0 |
| altitude | 10171.262255 | 10171.55043 | ft | 0 |
| airspeed | 250.311183 | 250.321259 | kt | 0 |
| height_agl | 10172.316834 | 10173.495536 | ft | 0 |
| vertical_speed | -0.063582 | 0.049552 | ft/s | 0 |
| bank | -0.05412 | -0.054058 | deg | 0 |

Recorded automation/contact value counts:

- main_gear_1_wow: {'false': 81}; unavailable: 0.
- main_gear_2_wow: {'false': 81}; unavailable: 0.
- autopilot_1: {'true': 81}; unavailable: 0.
- autopilot_2: {'false': 81}; unavailable: 0.
- autothrust: {'true': 81}; unavailable: 0.

Observation-file SHA-256: `f763b14f2b8bdb6944c1657c7672b2ac7a4acd02d86dd10f5e79da6754e49be1`.

## Limits

- Only two explicitly named public observation inputs enter inference; no manifests, private labels, actions, admission or phase files are read.
- InputA/inputB are identifiers, not claims of distinct physical initiating causes.
- Separate recordings need not be byte-identical and are not treated as independent statistical trials or a diagnosis-accuracy benchmark.
- Source/inventory/pressure compatibility rules are illustrative project choices; no root probabilities, unique causal identification or real-aircraft validation is computed.
- All-input ranges include every recorded sample; category-conditioned ranges select only by public-prefix analysis, never operator phases.
- Retained bus voltage and stable automated motion do not establish every actuator's capability or whole-aircraft health.
- Raw quantity units remain unresolved; any native automatic refill is not proof of physical repair.
- Different simulator clocks, receipt times, conditions and sampling offsets prevent direct byte-for-byte trajectory comparisons from establishing causal differences.

s means recorded simulator seconds, V volts, psi pounds per square inch, ft feet, kt knots (one nautical mile per hour), and AC alternating current. Quantity uses raw native units. Source hashes and exact archives are in provenance.json.

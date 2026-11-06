# AeroTrace causal diagnosis

Outcome: **causal_ambiguity**.
Public observations: 80; method: `dependency_compatibility_with_temporal_constraints`.

Explanation scope: {"closed": true, "end_sample_index": 77, "epoch": 0, "incident_id": "I0001", "kind": "last_observed_incident", "reference_sample_index": 17, "start_sample_index": 18}

Compatible model candidates: independent_pair, grouped_joint_event
Plausible candidates awaiting evidence: none

A surviving model configuration does not establish a unique physical cause or probability.

**What could reduce uncertainty.**
- Both candidates have identical predicted effects and temporal rules across the selected observation model. No available modeled measurement can establish their initiating history.

**Executable dependency model.** Conditional links permit retained downstream supply.

```mermaid
flowchart LR
    generator_2_source_path_fault -->|required| generator_source_anomaly
    generator_source_anomaly -->|conditional| bus_supply_loss
    blue_fluid_loss_mechanism -->|required| blue_inventory_loss
    blue_inventory_loss -->|conditional| blue_pressure_loss
```

**Confirmed incident degradation.**
- Generator-2 source-output degradation was observed in this incident. Bus observations are separate; source loss does not establish total downstream supply loss. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- Blue inventory depletion was observed in this incident. Raw inventory units and actuator capability remain unresolved; pressure is assessed separately. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- Blue pressure degradation was observed in this incident. Pressure degradation does not establish total controllability or manual-control force. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.

**Current observed impact.**
No selected confirmed impact in this scope; this is not a whole-aircraft health statement.

**Hypothesis: No selected mechanism currently required** (`selected_reference`).
Status: `contradicted`.
Supporting evidence:
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 77: 115.000789 V.
Contradicting evidence:
- generator source anomaly: This observed effect is not explained by the candidate's selected dependency paths. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
Predicted consequences:
- generator source anomaly: This observed effect is not explained by the candidate's selected dependency paths. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
Possible dependency paths:
- None recorded for this candidate.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: independent_pair, grouped_joint_event

**Hypothesis: Generator 2 source-path fault** (`generator_2_source_path_fault`).
Status: `contradicted`.
Supporting evidence:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 77: 115.000789 V.
Contradicting evidence:
- blue inventory loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
Predicted consequences:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: independent_pair, grouped_joint_event

**Hypothesis: Blue fluid-inventory-loss analogue** (`blue_inventory_loss`).
Status: `contradicted`.
Supporting evidence:
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
- The observed inventory-loss bracket precedes the pressure-loss bracket; this supports the qualitative selected depletion path, not an exact physical delay. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_pressure at sample 50: 2380.0 psi.
Contradicting evidence:
- generator source anomaly: This observed effect is not explained by the candidate's selected dependency paths. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
Predicted consequences:
- generator source anomaly: This observed effect is not explained by the candidate's selected dependency paths. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
Possible dependency paths:
- blue_fluid_loss_mechanism -> blue_inventory_loss (required). The selected fluid-loss analogue predicts inventory decline from an observed reference.
- blue_fluid_loss_mechanism -> blue_inventory_loss -> blue_pressure_loss (conditional). The selected fluid-loss analogue predicts inventory decline from an observed reference. Pressure can degrade as inventory/supply becomes insufficient; early retained pressure and subsequent restoration lag are allowed. No exact delay is assumed.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: independent_pair, grouped_joint_event

**Hypothesis: Independent source-path and blue inventory-loss mechanisms** (`independent_pair`).
Status: `compatible`.
Supporting evidence:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
- The observed inventory-loss bracket precedes the pressure-loss bracket; this supports the qualitative selected depletion path, not an exact physical delay. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_pressure at sample 50: 2380.0 psi.
Contradicting evidence:
- None recorded for this candidate.
Predicted consequences:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
- blue_fluid_loss_mechanism -> blue_inventory_loss (required). The selected fluid-loss analogue predicts inventory decline from an observed reference.
- blue_fluid_loss_mechanism -> blue_inventory_loss -> blue_pressure_loss (conditional). The selected fluid-loss analogue predicts inventory decline from an observed reference. Pressure can degrade as inventory/supply becomes insufficient; early retained pressure and subsequent restoration lag are allowed. No exact delay is assumed.
Missing evidence:
- Both candidates have identical predicted effects and temporal rules across the selected observation model. No available modeled measurement can establish their initiating history.
Alternative compatible candidates: grouped_joint_event

**Hypothesis: One grouped event affecting both selected mechanisms** (`grouped_joint_event`).
Status: `compatible`.
Supporting evidence:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
- The observed inventory-loss bracket precedes the pressure-loss bracket; this supports the qualitative selected depletion path, not an exact physical delay. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_pressure at sample 50: 2380.0 psi.
Contradicting evidence:
- None recorded for this candidate.
Predicted consequences:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 19: 0.0 V; generator_2_voltage at sample 70: 0.0 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 20: 7.466667 raw model quantity; blue_quantity at sample 70: 0.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 77: 115.000789 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 50: 2380.0 psi; blue_pressure at sample 75: 2166.666667 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
- blue_fluid_loss_mechanism -> blue_inventory_loss (required). The selected fluid-loss analogue predicts inventory decline from an observed reference.
- blue_fluid_loss_mechanism -> blue_inventory_loss -> blue_pressure_loss (conditional). The selected fluid-loss analogue predicts inventory decline from an observed reference. Pressure can degrade as inventory/supply becomes insufficient; early retained pressure and subsequent restoration lag are allowed. No exact delay is assumed.
Missing evidence:
- Both candidates have identical predicted effects and temporal rules across the selected observation model. No available modeled measurement can establish their initiating history.
Alternative compatible candidates: independent_pair

**Diagnostic timeline.**

| Sample | Epoch | Simulator seconds | Status | Compatible candidates |
|---:|---:|---:|---|---|
| 0 | 0 | 354.025 | insufficient_observations |  |
| 1 | 0 | 355.025 | no_selected_anomaly | selected_reference |
| 2 | 0 | 356.033333 | no_selected_anomaly | selected_reference |
| 3 | 0 | 357.025 | no_selected_anomaly | selected_reference |
| 4 | 0 | 358.033333 | no_selected_anomaly | selected_reference |
| 5 | 0 | 359.025 | no_selected_anomaly | selected_reference |
| 6 | 0 | 360.05 | no_selected_anomaly | selected_reference |
| 7 | 0 | 361.016667 | no_selected_anomaly | selected_reference |
| 8 | 0 | 362.025 | no_selected_anomaly | selected_reference |
| 9 | 0 | 363.025 | no_selected_anomaly | selected_reference |
| 10 | 0 | 364.025 | no_selected_anomaly | selected_reference |
| 11 | 0 | 365.041667 | no_selected_anomaly | selected_reference |
| 12 | 0 | 366.041667 | no_selected_anomaly | selected_reference |
| 13 | 0 | 367.025 | no_selected_anomaly | selected_reference |
| 14 | 0 | 368.033333 | no_selected_anomaly | selected_reference |
| 15 | 0 | 369.033333 | no_selected_anomaly | selected_reference |
| 16 | 0 | 370.025 | no_selected_anomaly | selected_reference |
| 17 | 0 | 371.033333 | no_selected_anomaly | selected_reference |
| 18 | 0 | 371.608333 | insufficient_observations |  |
| 19 | 0 | 372.616667 | insufficient_observations |  |
| 20 | 0 | 373.608333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 21 | 0 | 374.608333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 22 | 0 | 375.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 23 | 0 | 376.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 24 | 0 | 377.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 25 | 0 | 378.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 26 | 0 | 379.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 27 | 0 | 380.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 28 | 0 | 381.608333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 29 | 0 | 382.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 30 | 0 | 383.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 31 | 0 | 384.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 32 | 0 | 385.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 33 | 0 | 386.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 34 | 0 | 387.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 35 | 0 | 388.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 36 | 0 | 389.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 37 | 0 | 390.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 38 | 0 | 391.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 39 | 0 | 392.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 40 | 0 | 393.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 41 | 0 | 394.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 42 | 0 | 395.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 43 | 0 | 396.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 44 | 0 | 397.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 45 | 0 | 398.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 46 | 0 | 399.616667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 47 | 0 | 400.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 48 | 0 | 401.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 49 | 0 | 402.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 50 | 0 | 403.65 | causal_ambiguity | independent_pair, grouped_joint_event |
| 51 | 0 | 404.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 52 | 0 | 405.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 53 | 0 | 406.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 54 | 0 | 407.641667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 55 | 0 | 408.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 56 | 0 | 409.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 57 | 0 | 410.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 58 | 0 | 411.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 59 | 0 | 412.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 60 | 0 | 413.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 61 | 0 | 414.641667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 62 | 0 | 415.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 63 | 0 | 416.641667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 64 | 0 | 417.633333 | causal_ambiguity | independent_pair, grouped_joint_event |
| 65 | 0 | 418.641667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 66 | 0 | 419.641667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 67 | 0 | 420.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 68 | 0 | 421.641667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 69 | 0 | 422.625 | causal_ambiguity | independent_pair, grouped_joint_event |
| 70 | 0 | 423.641667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 71 | 0 | 424.2 | causal_ambiguity | independent_pair, grouped_joint_event |
| 72 | 0 | 425.191667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 73 | 0 | 426.2 | causal_ambiguity | independent_pair, grouped_joint_event |
| 74 | 0 | 427.2 | causal_ambiguity | independent_pair, grouped_joint_event |
| 75 | 0 | 428.2 | causal_ambiguity | independent_pair, grouped_joint_event |
| 76 | 0 | 429.2 | causal_ambiguity | independent_pair, grouped_joint_event |
| 77 | 0 | 430.2 | causal_ambiguity | independent_pair, grouped_joint_event |
| 78 | 0 | 431.216667 | causal_ambiguity | independent_pair, grouped_joint_event |
| 79 | 0 | 432.2 | causal_ambiguity | independent_pair, grouped_joint_event |

**Limits.**
- Five bounded candidate configurations reuse two verified native mechanisms; this is not complete aircraft diagnosis.
- A compatible model candidate is not a uniquely identified physical component failure or calibrated probability.
- The grouped joint-event and independent pair have identical observable predictions in this model; no available observation is invented to distinguish them.
- Incident-history hypotheses and confirmed incident degradation remain separate from current recovered or unavailable readings.
- The simulator and diagnostic model are related engineering abstractions, not independent real-aircraft validation.
- Temporal constraints are qualitative model assumptions; native depletion rates and exact propagation delays are not fitted signatures.
- The first offline path uses repeated prefix analysis; computation and memory suitability for a live display require separate measurement.

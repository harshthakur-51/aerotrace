# AeroTrace causal diagnosis

Outcome: **single_compatible_candidate**.
Public observations: 53; method: `dependency_compatibility_with_temporal_constraints`.

Explanation scope: {"closed": true, "end_sample_index": 49, "epoch": 0, "incident_id": "I0001", "kind": "last_observed_incident", "reference_sample_index": 21, "start_sample_index": 22}

Compatible model candidates: blue_pressure_supply_loss
Plausible candidates awaiting evidence: none

A surviving model configuration does not establish a unique physical cause or probability.

**What could reduce uncertainty.**
No additional selected discriminator is identified for the surviving configuration.

**Executable dependency model.** Conditional links permit retained downstream supply.

```mermaid
flowchart LR
    generator_2_source_path_fault -->|required| generator_source_anomaly
    generator_source_anomaly -->|conditional| bus_supply_loss
    blue_fluid_loss_mechanism -->|required| blue_inventory_loss
    blue_inventory_loss -->|conditional| blue_pressure_loss
    blue_pressure_supply_loss -->|required| blue_pressure_loss
```

**Confirmed incident degradation.**
- Blue pressure degradation was observed in this incident. Pressure degradation does not establish total controllability or manual-control force. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.

**Current observed impact.**
No selected confirmed impact in this scope; this is not a whole-aircraft health statement.

**Hypothesis: No selected mechanism currently required** (`selected_reference`).
Status: `contradicted`.
Supporting evidence:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 49: 115.000303 V.
Contradicting evidence:
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Predicted consequences:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- None recorded for this candidate.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: blue_pressure_supply_loss

**Hypothesis: Generator 2 source-path fault** (`generator_2_source_path_fault`).
Status: `contradicted`.
Supporting evidence:
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
Contradicting evidence:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Predicted consequences:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This observed effect is not explained by the candidate's selected dependency paths. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: blue_pressure_supply_loss

**Hypothesis: Blue fluid-inventory-loss analogue** (`blue_inventory_loss`).
Status: `contradicted`.
Supporting evidence:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Contradicting evidence:
- blue inventory loss: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
Predicted consequences:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- blue_fluid_loss_mechanism -> blue_inventory_loss (required). The selected fluid-loss analogue predicts inventory decline from an observed reference.
- blue_fluid_loss_mechanism -> blue_inventory_loss -> blue_pressure_loss (conditional). The selected fluid-loss analogue predicts inventory decline from an observed reference. Pressure can degrade as inventory/supply becomes insufficient; early retained pressure and subsequent restoration lag are allowed. No exact delay is assumed.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: blue_pressure_supply_loss

**Hypothesis: Independent source-path and blue inventory-loss mechanisms** (`independent_pair`).
Status: `contradicted`.
Supporting evidence:
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Contradicting evidence:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
Predicted consequences:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
- blue_fluid_loss_mechanism -> blue_inventory_loss (required). The selected fluid-loss analogue predicts inventory decline from an observed reference.
- blue_fluid_loss_mechanism -> blue_inventory_loss -> blue_pressure_loss (conditional). The selected fluid-loss analogue predicts inventory decline from an observed reference. Pressure can degrade as inventory/supply becomes insufficient; early retained pressure and subsequent restoration lag are allowed. No exact delay is assumed.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: blue_pressure_supply_loss

**Hypothesis: One grouped event affecting both selected mechanisms** (`grouped_joint_event`).
Status: `contradicted`.
Supporting evidence:
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Contradicting evidence:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
Predicted consequences:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
- blue_fluid_loss_mechanism -> blue_inventory_loss (required). The selected fluid-loss analogue predicts inventory decline from an observed reference.
- blue_fluid_loss_mechanism -> blue_inventory_loss -> blue_pressure_loss (conditional). The selected fluid-loss analogue predicts inventory decline from an observed reference. Pressure can degrade as inventory/supply becomes insufficient; early retained pressure and subsequent restoration lag are allowed. No exact delay is assumed.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: blue_pressure_supply_loss

**Hypothesis: Blue pressure-supply-path loss** (`blue_pressure_supply_loss`).
Status: `compatible`.
Supporting evidence:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Contradicting evidence:
- None recorded for this candidate.
Predicted consequences:
- generator source anomaly: Usable observation agrees with the executable dependency prediction. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: Usable observation agrees with the executable dependency prediction. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- blue_pressure_supply_loss -> blue_pressure_loss (required). The represented net blue pressure-supply-path loss predicts degraded pressure without requiring inventory loss; alternate supply and component identity are not observed.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: none

**Hypothesis: Independent source-path and blue pressure-supply losses** (`independent_pressure_pair`).
Status: `contradicted`.
Supporting evidence:
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Contradicting evidence:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
Predicted consequences:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
- blue_pressure_supply_loss -> blue_pressure_loss (required). The represented net blue pressure-supply-path loss predicts degraded pressure without requiring inventory loss; alternate supply and component identity are not observed.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: blue_pressure_supply_loss

**Hypothesis: One grouped event affecting source and blue pressure supply** (`grouped_pressure_joint_event`).
Status: `contradicted`.
Supporting evidence:
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Contradicting evidence:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
Predicted consequences:
- generator source anomaly: The candidate requires this effect, but it is not observed in the supplied incident scope. Evidence: generator_2_voltage at sample 49: 115.000303 V.
- blue inventory loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_quantity at sample 49: 8.0 raw model quantity.
- bus supply loss: This downstream effect is conditional; either retained or degraded output is compatible. Evidence: ac_bus_2 at sample 49: 115.000303 V.
- blue pressure loss: Usable observation agrees with the executable dependency prediction. Evidence: blue_pressure at sample 22: 2380.0 psi; blue_pressure at sample 47: 2100.0 psi.
Possible dependency paths:
- generator_2_source_path_fault -> generator_source_anomaly (required). The selected source-path mechanism predicts abnormal generator-2 output.
- generator_2_source_path_fault -> generator_source_anomaly -> bus_supply_loss (conditional). The selected source-path mechanism predicts abnormal generator-2 output. Downstream supply can be lost if alternate supply is unavailable; retained bus voltage is compatible and does not identify its supply route.
- blue_pressure_supply_loss -> blue_pressure_loss (required). The represented net blue pressure-supply-path loss predicts degraded pressure without requiring inventory loss; alternate supply and component identity are not observed.
Missing evidence:
- None recorded for this candidate.
Alternative compatible candidates: blue_pressure_supply_loss

**Diagnostic timeline.**

| Sample | Epoch | Simulator seconds | Status | Compatible candidates |
|---:|---:|---:|---|---|
| 0 | 0 | 275.141667 | insufficient_observations |  |
| 1 | 0 | 276.141667 | no_selected_anomaly | selected_reference |
| 2 | 0 | 277.141667 | no_selected_anomaly | selected_reference |
| 3 | 0 | 278.141667 | no_selected_anomaly | selected_reference |
| 4 | 0 | 279.15 | no_selected_anomaly | selected_reference |
| 5 | 0 | 280.141667 | no_selected_anomaly | selected_reference |
| 6 | 0 | 281.141667 | no_selected_anomaly | selected_reference |
| 7 | 0 | 282.158333 | no_selected_anomaly | selected_reference |
| 8 | 0 | 283.141667 | no_selected_anomaly | selected_reference |
| 9 | 0 | 284.141667 | no_selected_anomaly | selected_reference |
| 10 | 0 | 285.15 | no_selected_anomaly | selected_reference |
| 11 | 0 | 286.15 | no_selected_anomaly | selected_reference |
| 12 | 0 | 287.15 | no_selected_anomaly | selected_reference |
| 13 | 0 | 288.141667 | no_selected_anomaly | selected_reference |
| 14 | 0 | 289.15 | no_selected_anomaly | selected_reference |
| 15 | 0 | 290.141667 | no_selected_anomaly | selected_reference |
| 16 | 0 | 291.15 | no_selected_anomaly | selected_reference |
| 17 | 0 | 292.166667 | no_selected_anomaly | selected_reference |
| 18 | 0 | 292.625 | no_selected_anomaly | selected_reference |
| 19 | 0 | 293.625 | no_selected_anomaly | selected_reference |
| 20 | 0 | 294.625 | no_selected_anomaly | selected_reference |
| 21 | 0 | 295.616667 | no_selected_anomaly | selected_reference |
| 22 | 0 | 296.633333 | single_compatible_candidate | blue_pressure_supply_loss |
| 23 | 0 | 297.625 | single_compatible_candidate | blue_pressure_supply_loss |
| 24 | 0 | 298.65 | single_compatible_candidate | blue_pressure_supply_loss |
| 25 | 0 | 299.633333 | single_compatible_candidate | blue_pressure_supply_loss |
| 26 | 0 | 300.625 | single_compatible_candidate | blue_pressure_supply_loss |
| 27 | 0 | 301.633333 | single_compatible_candidate | blue_pressure_supply_loss |
| 28 | 0 | 302.616667 | single_compatible_candidate | blue_pressure_supply_loss |
| 29 | 0 | 303.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 30 | 0 | 304.65 | single_compatible_candidate | blue_pressure_supply_loss |
| 31 | 0 | 305.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 32 | 0 | 306.625 | single_compatible_candidate | blue_pressure_supply_loss |
| 33 | 0 | 307.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 34 | 0 | 308.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 35 | 0 | 309.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 36 | 0 | 310.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 37 | 0 | 311.658333 | single_compatible_candidate | blue_pressure_supply_loss |
| 38 | 0 | 312.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 39 | 0 | 313.633333 | single_compatible_candidate | blue_pressure_supply_loss |
| 40 | 0 | 314.641667 | single_compatible_candidate | blue_pressure_supply_loss |
| 41 | 0 | 315.675 | single_compatible_candidate | blue_pressure_supply_loss |
| 42 | 0 | 316.65 | single_compatible_candidate | blue_pressure_supply_loss |
| 43 | 0 | 317.091667 | single_compatible_candidate | blue_pressure_supply_loss |
| 44 | 0 | 318.091667 | single_compatible_candidate | blue_pressure_supply_loss |
| 45 | 0 | 319.091667 | single_compatible_candidate | blue_pressure_supply_loss |
| 46 | 0 | 320.083333 | single_compatible_candidate | blue_pressure_supply_loss |
| 47 | 0 | 321.083333 | single_compatible_candidate | blue_pressure_supply_loss |
| 48 | 0 | 322.1 | single_compatible_candidate | blue_pressure_supply_loss |
| 49 | 0 | 323.083333 | single_compatible_candidate | blue_pressure_supply_loss |
| 50 | 0 | 324.091667 | single_compatible_candidate | blue_pressure_supply_loss |
| 51 | 0 | 325.083333 | single_compatible_candidate | blue_pressure_supply_loss |
| 52 | 0 | 326.083333 | single_compatible_candidate | blue_pressure_supply_loss |

**Limits.**
- Eight configurations represent three selected mechanism classes; native confirmation and scope are documented separately. This is not complete aircraft diagnosis.
- A compatible model candidate is not a uniquely identified physical component failure or calibrated probability.
- The grouped joint-event and independent pair have identical observable predictions in this model; no available observation is invented to distinguish them.
- Incident-history hypotheses and confirmed incident degradation remain separate from current recovered or unavailable readings.
- A valid, advancing quantity indication can still be wrong. Physical fluid loss requires independent corroboration.
- The simulator and diagnostic model are related engineering abstractions, not independent real-aircraft validation.
- Temporal constraints are qualitative model assumptions; native depletion rates and exact propagation delays are not fitted signatures.
- The first offline path uses repeated prefix analysis; computation and memory suitability for a live display require separate measurement.

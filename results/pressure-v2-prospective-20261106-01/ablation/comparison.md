# AeroTrace method comparison

Declared analysis role: `post_prediction_descriptive`.

Identical extracted facts/catalogue; only model temporal constraints change between dependency methods.
Alert-only reports effects and performs no cause inference. These are descriptive comparisons, not accuracy scores.

| Explicit input | Polls | Final dependency | Final temporal | Prefixes with changed result |
|---|---:|---|---|---:|
| results\pressure-v2-prospective-20261106-01\episode-A-01\observations.jsonl | 32 | no_selected_anomaly: selected_reference | no_selected_anomaly: selected_reference | 0 |
| results\pressure-v2-prospective-20261106-01\episode-A-02\observations.jsonl | 53 | single_compatible_candidate: blue_pressure_supply_loss | single_compatible_candidate: blue_pressure_supply_loss | 0 |
| results\pressure-v2-prospective-20261106-01\episode-A-03\observations.jsonl | 53 | causal_ambiguity: independent_pressure_pair, grouped_pressure_joint_event | causal_ambiguity: independent_pressure_pair, grouped_pressure_joint_event | 0 |
| results\pressure-v2-prospective-20261106-01\episode-B-01\observations.jsonl | 32 | no_selected_anomaly: selected_reference | no_selected_anomaly: selected_reference | 0 |
| results\pressure-v2-prospective-20261106-01\episode-B-02\observations.jsonl | 53 | single_compatible_candidate: blue_pressure_supply_loss | single_compatible_candidate: blue_pressure_supply_loss | 0 |
| results\pressure-v2-prospective-20261106-01\episode-B-03\observations.jsonl | 53 | causal_ambiguity: independent_pressure_pair, grouped_pressure_joint_event | causal_ambiguity: independent_pressure_pair, grouped_pressure_joint_event | 0 |

Changed-prefix counts describe correlated views of whole recordings, not independent successes.
Zero changes must be reported as no observed discrimination gain on that input, not concealed.
The saved model, shared facts and candidate contradictions make each method comparison inspectable.
No hidden/private truth, injected physical-cause label or ground-truth scoring enters this command.

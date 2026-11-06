# AeroTrace development method comparison

Identical extracted facts/catalogue; only model temporal constraints change between dependency methods.
Alert-only reports effects and performs no cause inference. These are development replays, not accuracy scores.

| Explicit input | Polls | Final dependency | Final temporal | Prefixes with changed result |
|---|---:|---|---|---:|
| results\prospective-pilot-20261103-01\episode-001\observations.jsonl | 31 | no_selected_anomaly: selected_reference | no_selected_anomaly: selected_reference | 0 |
| results\prospective-pilot-20261103-01\episode-002\observations.jsonl | 33 | single_compatible_candidate: generator_2_source_path_fault | single_compatible_candidate: generator_2_source_path_fault | 0 |
| results\prospective-pilot-20261103-01\episode-003\observations.jsonl | 80 | single_compatible_candidate: blue_inventory_loss | single_compatible_candidate: blue_inventory_loss | 0 |
| results\prospective-pilot-20261103-01\episode-004\observations.jsonl | 81 | causal_ambiguity: independent_pair, grouped_joint_event | causal_ambiguity: independent_pair, grouped_joint_event | 0 |

Changed-prefix counts describe correlated views of whole recordings, not independent successes.
Zero changes must be reported as no observed discrimination gain on that input, not concealed.
The saved model, shared facts and candidate contradictions make each method comparison inspectable.
No hidden/private truth, injected physical-cause label or ground-truth scoring enters this command.

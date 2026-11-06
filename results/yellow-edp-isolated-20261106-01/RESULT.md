# Isolated Yellow engine-driven pump loss

The pinned FlightGear A320-200-CFM qualified near 6,090 feet and 231 knots with both engines running. The operator enabled only the Yellow engine-driven pump (EDP) failure input and left the power transfer unit (PTU) in automatic. The 60 complete public polls include 28.99 sampled simulator seconds during the intervention and 11.00 during recovery. [Declared test](PROTOCOL.md) · [Public recording](run/observations.jsonl) · [Operator summary](run/private_truth/summary.json)

| Observation | End of intervention | Final recorded value |
| --- | ---: | ---: |
| Engine 2 core speed | 77.6% | 77.6% |
| Generator 2 output | 115.0 volts | 115.0 volts |
| Yellow EDP output | 0 psi | 3,000 psi |
| Green-to-Yellow transfer | 2,700 psi | 0 psi |
| Yellow line pressure | 2,700 psi | 3,000 psi |
| Yellow reservoir indication | 15 raw model units | 15 raw model units |

The intervention values are medians of the final six active polls. Core speed is a percentage of the simulator reference high-pressure spool speed. Psi means pounds per square inch. The two samples bracketing the observed Yellow pump output loss were at 202.47 and 203.22 simulator seconds. The bracket describes the observed change. [Generated replay check](generated-check.json)

The live version 3 diagnosis and its public replay agreed. Version 4 generated all 32 mechanism sets and found one minimal fit, **local Yellow engine-driven pump loss**, at **100% evidence support (8 of 8 checks)**. The measured transfer explained retained line pressure. After clearing, pump and line pressure recovered and the incident closed. The native control readback confirmed all studied failure inputs clear. [Five-fault study](../../docs/FAULT-SEQUENCE-STUDY.md)

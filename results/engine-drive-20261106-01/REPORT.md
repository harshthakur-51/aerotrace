# Engine 2 drive-loss contrast results

Each row represents a whole native run. Measurements are medians of the six declared end-of-intervention polls.

| Run | Fuel flow (lb/h) | Core speed (%) | Gen 2 (V) | Yellow pump (psi) | Transfer (psi) | Yellow line (psi) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pair-auto | 3,555.1 | 77.6 | 0.0 | 0.0 | 2,700.0 | 2,700.0 |
| engine-auto | 0.0 | 11.9 | 0.0 | 0.0 | 2,700.0 | 2,700.0 |
| pair-off | 3,552.8 | 77.6 | 0.0 | 0.0 | 0.0 | 0.0 |
| engine-off | 0.0 | 11.9 | 0.0 | 0.0 | 0.0 | 0.0 |

Fuel flow is measured in pounds per hour (lb/h). Core speed is measured as a percentage of the simulator's reference high-pressure spool speed. V means volts and psi means pounds per square inch.

| Run | Full input | Fuel flow and core speed withheld | Alternate pressure measurements withheld |
| --- | --- | --- | --- |
| pair-auto | Separate generator and Yellow pump losses (100% support) | 2 plausible, 0 confirmed (71%, 71%) | Supply check unknown (86% support) |
| engine-auto | Engine 2 power loss (100% support) | 2 plausible, 0 confirmed (71%, 71%) | Supply check unknown (86% support) |
| pair-off | Separate generator and Yellow pump losses (100% support) | 2 plausible, 0 confirmed (71%, 71%) | Supply check unknown (86% support) |
| engine-off | Engine 2 power loss (100% support) | 2 plausible, 0 confirmed (71%, 71%) | Supply check unknown (86% support) |

Matched the predeclared candidate in **4 of 4** runs. Streaming and replay agreed in **4 of 4** runs.

The percentage measures model checks supported by the available observations. The tested contrasts use one pinned simulator and target flight condition.

[Full evidence and onset intervals](study.json)

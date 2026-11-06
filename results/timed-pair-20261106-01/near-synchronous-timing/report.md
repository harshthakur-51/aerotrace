# AeroTrace incident timing

Times are simulator seconds. Each window spans sampled states. Evidence support counts corroborated model checks. Physical cause probability remains unresolved.

Declared response bounds: {"generator_source_anomaly": [0, 3], "blue_pressure_loss": [0, 10]}

## I0001

Observed onset order: **generator before pressure**.
Bounded shared trigger: **consistent**.

| Effect | Observed onset (s) | Plausible trigger (s) |
| --- | --- | --- |
| generator source anomaly | 376.86 to 377.53 | 373.86 to 377.53 |
| blue pressure loss | 380.56 to 381.57 | 370.56 to 381.57 |

| State | Samples | Simulator time (s) |
| --- | --- | --- |
| both nominal | 16 to 16 | 376.79 to 376.79 |
| unknown | 17 to 17 | 377.46 to 377.46 |
| generator only | 18 to 20 | 378.45 to 380.46 |
| both degraded | 21 to 42 | 381.47 to 402.47 |
| pressure only | 43 to 47 | 403.09 to 407.10 |
| both nominal | 48 to 49 | 408.08 to 409.09 |

| Candidate | Fit | Evidence support |
| --- | --- | --- |
| No selected mechanism currently required | contradicted | Excluded |
| Generator 2 source-path fault | contradicted | Excluded |
| Blue fluid-inventory-loss analogue | contradicted | Excluded |
| Independent source-path and blue inventory-loss mechanisms | contradicted | Excluded |
| One grouped event affecting both selected mechanisms | contradicted | Excluded |
| Blue pressure-supply-path loss | contradicted | Excluded |
| Independent source-path and blue pressure-supply losses | compatible | 100% (3 of 3) |
| One shared trigger within the declared response bounds | compatible | 100% (4 of 4) |

# AeroTrace incident timing

Times are simulator seconds. Each window spans sampled states. Evidence support counts corroborated model checks. Physical cause probability remains unresolved.

Declared response bounds: {"generator_source_anomaly": [0, 3], "blue_pressure_loss": [0, 10]}

## I0001

Observed onset order: **generator before pressure**.
Bounded shared trigger: **contradicted**.

| Effect | Observed onset (s) | Plausible trigger (s) |
| --- | --- | --- |
| generator source anomaly | 223.52 to 224.03 | 220.52 to 224.03 |
| blue pressure loss | 243.65 to 244.66 | 233.65 to 244.66 |

| State | Samples | Simulator time (s) |
| --- | --- | --- |
| both nominal | 16 to 16 | 223.45 to 223.45 |
| unknown | 17 to 17 | 223.95 to 223.95 |
| generator only | 18 to 37 | 224.97 to 243.56 |
| both degraded | 38 to 49 | 244.57 to 255.58 |
| pressure only | 50 to 68 | 255.99 to 273.39 |
| both nominal | 69 to 70 | 274.41 to 275.40 |

| Candidate | Fit | Evidence support |
| --- | --- | --- |
| No selected mechanism currently required | contradicted | Excluded |
| Generator 2 source-path fault | contradicted | Excluded |
| Blue fluid-inventory-loss analogue | contradicted | Excluded |
| Independent source-path and blue inventory-loss mechanisms | contradicted | Excluded |
| One grouped event affecting both selected mechanisms | contradicted | Excluded |
| Blue pressure-supply-path loss | contradicted | Excluded |
| Independent source-path and blue pressure-supply losses | compatible | 100% (3 of 3) |
| One shared trigger within the declared response bounds | contradicted under response bounds | Excluded |

# AeroTrace incident timing

Times are simulator seconds. Each window spans sampled states. Evidence support counts corroborated model checks. Physical cause probability remains unresolved.

Declared response bounds: {"generator_source_anomaly": [0, 3], "blue_pressure_loss": [0, 10]}

## I0001

Observed onset order: **unresolved**.
Bounded shared trigger: **not applicable**.

| State | Samples | Simulator time (s) |
| --- | --- | --- |
| both nominal | 17 to 17 | 298.93 to 298.93 |
| unknown | 18 to 18 | 299.38 to 299.38 |
| generator only | 19 to 27 | 300.38 to 308.38 |
| both nominal | 28 to 29 | 308.75 to 309.76 |

| Candidate | Fit | Evidence support |
| --- | --- | --- |
| No selected mechanism currently required | contradicted | Excluded |
| Generator 2 source-path fault | compatible | 100% (3 of 3) |
| Blue fluid-inventory-loss analogue | contradicted | Excluded |
| Independent source-path and blue inventory-loss mechanisms | contradicted | Excluded |
| One grouped event affecting both selected mechanisms | contradicted | Excluded |
| Blue pressure-supply-path loss | contradicted | Excluded |
| Independent source-path and blue pressure-supply losses | contradicted | Excluded |
| One shared trigger within the declared response bounds | contradicted | Excluded |

## I0002

Observed onset order: **unresolved**.
Bounded shared trigger: **not applicable**.

| State | Samples | Simulator time (s) |
| --- | --- | --- |
| both nominal | 40 to 40 | 320.31 to 320.31 |
| pressure only | 41 to 66 | 321.31 to 345.78 |
| both nominal | 67 to 68 | 346.80 to 347.77 |

| Candidate | Fit | Evidence support |
| --- | --- | --- |
| No selected mechanism currently required | contradicted | Excluded |
| Generator 2 source-path fault | contradicted | Excluded |
| Blue fluid-inventory-loss analogue | contradicted | Excluded |
| Independent source-path and blue inventory-loss mechanisms | contradicted | Excluded |
| One grouped event affecting both selected mechanisms | contradicted | Excluded |
| Blue pressure-supply-path loss | compatible | 100% (4 of 4) |
| Independent source-path and blue pressure-supply losses | contradicted | Excluded |
| One shared trigger within the declared response bounds | contradicted | Excluded |

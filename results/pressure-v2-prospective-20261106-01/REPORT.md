# Version 2 prospective replication

Six predeclared episodes completed across two fresh FlightGear process launches.
The protocol fixed the temporal method, three-mechanism catalogue, detector,
source and scorer hashes, 21 known inputs and the run assignments before these
flights. Prediction used each public observation file in a separate process
before the corresponding private scoring target was written.
[Sealed plan](../pressure-v2-protocol-20261106-01/README.md)

| Flight group | Observed baseline | Reference polls | Isolated pump polls | Paired polls |
|---|---|---:|---:|---:|
| A | About 8,134 feet and 240 knots | 32 | 53 | 53 |
| B | About 6,096 feet and 231 knots | 32 | 53 | 53 |

All six final candidate sets matched their predeclared targets. Reference
episodes retained the selected reference. Both isolated pump episodes retained
the pressure-supply configuration. Both paired episodes retained the independent
and grouped pressure-pair configurations. Every final live result matched
offline replay, including evidence, impacts and the timing relation.

All 276 public polls were complete. In the pump and paired episodes, Blue pressure
reached zero while reported quantity stayed at 8 raw model units. Both monitored
alternating current buses stayed supplied. Generator 2 output reached zero during
both paired episodes and stayed available in both pump-only episodes. All supported
flags cleared after each episode. Backup turbine position read zero before and after
each run. The first owned FlightGear process was closed after its final readback.
The second was paused after clearing its last pair.

The post-prediction method comparison recorded zero changes in status or candidate
sets from the timing rule across the 276 correlated prefixes. These six episodes
cover the declared profiles at two conditions using the same aircraft model, airport
and fixed weather. They measure candidate-set agreement with the sealed specification.
The public signals still leave the physical initiating history unresolved.
[Per-episode results](cohort-summary.json) · [Method comparison](ablation/comparison.md)

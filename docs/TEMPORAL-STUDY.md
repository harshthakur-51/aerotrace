# Timed fault diagnosis

The same generator and pump faults can create a near-synchronous pair, overlapping failures with separate onsets, or two incidents with recovery between them. A final set of active fault labels loses those distinctions.

The [airborne runner](../aircraft_debugger/airborne_experiment.py) accepts a private JSON schedule with the active fault flags and duration of each phase in simulator seconds. A phase can hold one fault, a supported pair or a clear interval. The runner verifies a stable baseline and checks fresh flight state and owned flags before each later enable. It clears outgoing flags before setting new ones and records the actual observations through recovery. [Overlap schedule](../configs/timing-generator-then-pump.json) · [Recovery gap schedule](../configs/timing-separated-source-and-pump.json)

## What timing can establish

The [timing analysis](../aircraft_debugger/temporal_analysis.py) reads public observations. It retains separate incidents and reports sampled windows of generator degradation alone, pressure degradation alone, both, or neither. A missing, stale or unconfirmed reading leaves the joint state unknown. The two channel readings must be within a quarter of a simulator second for a joint state to be shown. Behavior between polls remains unresolved.

The optional [response bounds](../configs/timing-pump-response-bounds.json) describe a direct shared trigger with a generator effect within 0 to 3 simulator seconds and a Blue pressure effect within 0 to 10 simulator seconds. These are declared test assumptions for this study. The archived isolated and paired flights show a fast generator response and a slower pressure threshold crossing with no active backup turbine supply. Backup supply, delayed propagation and different conditions can change those responses. [Native paired recording](../results/pressure-pair-20261106-01/RESULT.md)

For each effect, the last nominal and first anomalous reading bracket its observed onset. The earliest plausible trigger is the earlier onset bound less the maximum response delay. The latest plausible trigger is the later onset bound less the minimum delay. All quantities here are in simulator seconds on the same clock epoch. A shared trigger must have a time inside both intervals. Disjoint intervals exclude the declared direct response model. Intersecting intervals leave it compatible alongside independent failures. A missing bracket or interrupted measurement coverage leaves the test unresolved. This is a project interval check implemented in [temporal_analysis.py](../aircraft_debugger/temporal_analysis.py).

## Evidence support percentage

The panel and timing report display the percentage of a candidate's applicable checks supported by the observations. The denominator includes required effect, required absence and applicable timing checks. An unknown check remains in the denominator. Optional effects such as retained or lost bus voltage contribute no credit when both are allowed. A contradiction excludes the candidate and suppresses its percentage. The display rounds to a whole percentage and shows the counts. This is a project evidence coverage measure, implemented in [candidate_support.py](../aircraft_debugger/candidate_support.py).

Two candidates can each show 100% when every check is supported for both. Candidate probabilities would require distinguishable initiating histories and a calibration set with independent truth for those histories. The current observations establish compatibility and timing constraints.

## Airborne results

The two new schedules ran on the same FlightGear A320 flight near 6,100 ft (feet) and 231 kt (knots). The operator captured 76 polls for the staggered schedule and 73 for the recovery-gap schedule. All three native fault flags were verified clear after both runs. The comparison uses a previously recorded near-synchronous intervention at the same target condition. The analysis reads each public recording independently of its schedule and flag history.

| Recording | What the observations show | Diagnosis under the declared response bounds |
| --- | --- | --- |
| [Near-synchronous intervention](../results/timed-pair-20261106-01/near-synchronous-timing/report.md) | Generator effect begins 3.03–4.71 simulator seconds before the measured pressure effect. | Independent failures and a bounded shared trigger both fit. Evidence support is 100% for each. |
| [Staggered with overlap](../results/timed-pair-20261106-01/timing/report.md) | Generator effect begins 19.63–21.14 simulator seconds before the pressure effect. Generator-only readings give way to both effects, then pressure alone. | Independent failures fit with 100% support (3 of 3). The bounded shared trigger is excluded. |
| [Recovery gap](../results/timed-separated-20261106-01/timing/report.md) | Generator output recovers before the later pressure loss. No joint degradation was sampled. | Two closed incidents with distinct compatible candidates. Source-path loss has 100% support (3 of 3) and pressure-supply loss has 100% support (4 of 4). |

The staggered trace allows a shared trigger again if the assumed maximum pressure response delay is widened from 10 to 30 simulator seconds. The 30-second case is a sensitivity check on the same observations. It shows which assumption drives the exclusion and why delayed shared propagation remains possible. [Sensitivity replay](../results/timed-pair-20261106-01/wider-pressure-delay/report.md)

## Reproduce the chronology

```powershell
python -B -m aircraft_debugger.temporal_analysis --observations results/timed-pair-20261106-01/observations.jsonl --response-bounds configs/timing-pump-response-bounds.json --output work/staggered-timing-replay
```

The live and replay panel percentages cover the base candidate checks. Run the command above for the additional shared-trigger screen. For native collection with the supplied schedules, run `python -B -m aircraft_debugger.airborne_experiment --help` and use the `--schedule` option after qualifying the simulator for the experiment.

Relative measurement ordering and the limits introduced by masking and compensation motivate this test design. The implemented check uses AeroTrace's observed threshold intervals. [Daigle et al., Improving Multiple Fault Diagnosability using Possible Conflicts](https://ntrs.nasa.gov/citations/20140004901)

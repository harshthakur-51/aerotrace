# AeroTrace

An observability-aware diagnostic demonstrator for selected cross-system faults
in a locally running Airbus A320 simulation.

## Question

When a generator output disappears and hydraulic pressure falls, which explanations
fit the signals the debugger can observe? AeroTrace compares a finite set of causal
configurations, shows the evidence for and against each one, and retains a tie when
the available measurements support multiple initiating histories.

Qantas Flight 32 motivates the distinction between indications and physical causes.
The Australian Transport Safety Bureau traced widespread A380 systems damage to an
uncontained engine failure. The crew saw the Green hydraulic fluid level indication
fall. Investigators documented damage to the monitoring wiring and found no Green
fluid loss in the later examination. The A320 demonstrator uses the incident to
frame an observability problem. Its cases are selected native simulator interventions.
[ATSB final report, Appendix B, printed page 218](https://www.atsb.gov.au/sites/default/files/media/4173625/ao-2010-089_final.pdf)

## Implementation

FlightGear supplies the A320 dynamics and systems. A guarded operator collects
timestamped public measurements and saves fault commands and readiness checks in a
separate private record. Diagnosis receives the public observations. The same
detector and causal evaluator run in the live panel and recorded replay. The offline
scorer sees the sealed target only after a prediction exists.

The diagnostic model uses generator 2 output, alternating current bus 2 voltage,
reported Blue reservoir quantity and Blue hydraulic pressure. It represents expected
effects and conditional propagation. A generator can lose output while bus voltage
stays available. Reported quantity decline can precede pressure degradation. The
optional pressure-supply mechanism accounts for low pressure alongside retained
quantity. The timing rule checks whether the observation brackets contradict the
selected inventory-first path. These are project choices implemented in
`aircraft_debugger/hypotheses.py` and `aircraft_debugger/diagnostic_features.py`.

The result distinguishes compatible, contradicted and unconfirmed candidates.
Missing readings and conflicting effects are visible as insufficient observations
or poor model fit. The interface separates current measurements from earlier
incident evidence, which lets a reviewer inspect a resolved episode after recovery.
Version 1 is the default two-mechanism catalogue. Version 2 is an explicit
three-mechanism extension. [Architecture](ARCHITECTURE.md)

## Native result

A fresh A320 session at approximately 10,171 feet and 250 knots provided 53
complete public polls for the generator and Blue electric pump intervention.
Generator output reached zero volts, both monitored alternating current buses
stayed near 115 volts, and Blue pressure fell from 3,000 pounds per square inch
to zero. Reported quantity stayed at 8 raw model units. The ram air turbine
position read zero before and after the episode. All three supported fault flags
were clear after recovery. [Native recording and operator evidence](../results/pressure-pair-20261106-01/RESULT.md)

The figure uses each channel's recorded simulator timestamps. Lines connect
non-atomic observations. The pressure unit is pounds per square inch, shown as
psi. Quantity is shown in raw simulator units.
[Paired observations figure](figures/pressure-pair-observed.png)

| Replay samples | Version 2 temporal result |
|---|---|
| 1 through 17 | Selected reference |
| 18 | Insufficient observations for a settled candidate set |
| 19 through 21 | Generator 2 source-path configuration fits |
| 22 through 52 | Both pressure-pair configurations fit |

The paired result preserves independent and grouped explanations as observationally
equivalent. The result changes as hydraulic evidence arrives. A candidate shown early
in the incident describes the available evidence at that point. Live and offline
final diagnosis, evidence, impacts and timing relation matched.

## Evaluation

The first sealed version 1 pilot matched the predeclared candidate sets for four
episodes from one fresh flight. Its 225 public polls provide correlated evidence
within those episodes. The protocol bound the catalogue, detector, executed sources,
scorer and planned assignments. The held-out results measure bounded specification
compliance for the declared cases. [Version 1 pilot](../results/prospective-pilot-20261103-01/PILOT-REPORT.md)

Version 2 replicated three profiles across two fresh simulator sessions. All six
episodes matched their sealed candidate sets, with agreement between final live
and offline results. The first flight stabilized near 8,134 feet and 240 knots.
The second stabilized near 6,096 feet and 231 knots. Each flight included a
reference, a pump-only episode and a generator-plus-pump episode. The 276 polls
remain grouped by those two flights. The result supports bounded specification
compliance in the declared simulator conditions.
[Version 2 prospective results](../results/pressure-v2-prospective-20261106-01/REPORT.md)

The method ablation compares alert-only output, dependency compatibility and
dependency compatibility with the timing constraint. All methods receive identical
selected facts. The alert-only method emits the effects. The dependency methods
add candidate explanations and contradictions. Timing did not change candidate
discrimination in either native pilot. [Method comparison](METHOD-COMPARISON.md)

The quantity-integrity stress uses software substitutions of an isolated native pump
recording. An early false quantity decline shifted both dependency methods to the
inventory-loss configuration. A late false decline still fit the dependency method,
while the temporal method flagged poor fit. The test exposes a limit of timing checks
and a case in which they add a distinction. In the live and replay reports, a quantity
decrease is described as a reported indication. Independent evidence is needed to
verify physical fluid loss. [Stress inputs and results](../results/quantity-indication-stress-20261106-01/README.md)

## Update cost

The long-session fixture extends the active native pressure pair to 1,200 polls
with synthetic advancing timestamps. Reusing the live airborne context brought
the measured 95th-percentile adapter update from 490 to 80 milliseconds across
the two host runs. Background load differed between runs. The timing covers local
processing and snapshot copy. The optimized session matched all 276 archived
prospective prefixes and retained the explicit session limit.
[Load measurements and parity](../results/pressure-v2-load-optimized-20261106-01/REPORT.md)

## Demonstration

From the source folder with Python 3.11 or later, launch the recorded inspector.

```powershell
python -B -m aircraft_debugger.sim_panel --replay results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --port 8769
```

Open http://127.0.0.1:8769. Advance from sample 17 through sample 22. Expand the
two compatible pressure-pair explanations to compare their evidence. Advance to
the final sample and compare the restored current readings with the retained
incident. The recorded demo requires Python and the included public file.
[Reproduction guide](REPRODUCING.md)

The study covers selected simulator properties and three native mechanism analogues.
The public input lacks independent evidence of physical fluid loss, component identity
and common damage. Broader aircraft capability and crew performance remain outside
the evidence. The live prototype caps inference at 1,200 polls and exposes that limit
in the panel. The six-week submission focuses on the reproducible diagnostic method,
observed outcomes and failure analysis.

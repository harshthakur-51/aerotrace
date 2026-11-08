# AeroTrace

[![tests](https://github.com/harshthakur-51/aerotrace/actions/workflows/tests.yml/badge.svg)](https://github.com/harshthakur-51/aerotrace/actions/workflows/tests.yml)

**An evidence-driven debugger for cross-system failures in an Airbus A320 simulation.**

**Problem.** When several aircraft systems fail at once, the warnings show *effects*,
not *causes*. On Qantas Flight 32 an engine failure damaged hydraulic and electrical
systems, and the crew had to work out which warnings shared one origin.
[ATSB report AO-2010-089](https://www.atsb.gov.au/sites/default/files/media/4173625/ao-2010-089_final.pdf)

**Approach.** AeroTrace reads live or recorded telemetry from the FlightGear A320
simulator. It checks every combination of five modelled fault mechanisms against a
dependency graph of the electrical, hydraulic and propulsion systems. A combination
survives if none of its predicted effects contradicts the observations. Fault onset
timing further narrows which histories are possible. When the signals cannot tell two
explanations apart, AeroTrace keeps both and names the measurement that would separate them.

**Result.** In prospective tests on fresh simulator flights, the surviving explanations
matched the predeclared expected sets in all 6 planned episodes. A recorded Engine 2
failure is traced to one shared cause rather than separate generator and pump faults.
Detecting a hidden *physical* common cause (such as debris damage) from timing alone
does not work yet; see [Limitations](#limitations).

**Scope.** Five fault mechanism classes, one simulated aircraft (FlightGear A320-family,
pinned revision 20376), steady airborne flight at about 6,100 to 10,200 ft and 230 to
250 kt. Simulator data only; nothing here is validated against a real aircraft.

[v1.3 results](results/v1.3-investigation-20261107-01/REPORT.md) · [Architecture](docs/ARCHITECTURE.md) · [Reproduce the results](docs/REPRODUCING.md) · [Connect FlightGear](docs/LIVE-SIMULATOR.md)

## How it works

| Step | What happens | Code |
| --- | --- | --- |
| 1. Observe | Poll simulator properties (generator voltage, bus voltage, hydraulic pressure and quantity, engine core speed, fuel flow, pump outputs). Each reading keeps its own timestamp and validity flag. | [flightgear.py](aircraft_debugger/flightgear.py), [airborne_profile.py](aircraft_debugger/airborne_profile.py) |
| 2. Extract facts | Compare each channel with its reference period. Mark each effect as observed, absent or unknown, and bracket its onset time. Missing data stays unknown and is never treated as healthy. | [diagnostic_features.py](aircraft_debugger/diagnostic_features.py) |
| 3. Test explanations | The five mechanisms give 2^5 = 32 possible fault sets. Each set predicts required and conditional effects through the dependency graph. A set is excluded when an observed fact contradicts a required prediction. | [hypotheses.py](aircraft_debugger/hypotheses.py) |
| 4. Test timing | For the surviving sets, enumerate the possible fault onset orders (1,081 histories over all 31 non-empty sets, counting simultaneous onsets) and keep those consistent with the observed onset brackets. | [sequence_reasoning.py](aircraft_debugger/sequence_reasoning.py) |
| 5. Investigate | Answer "what if this cause is excluded?", flag faults that could be masked by another failure, and rank the measurement that would best split the remaining explanations. | [investigation.py](aircraft_debugger/investigation.py) |

The five mechanism classes are Generator 2 source loss, Blue hydraulic fluid inventory
loss, Blue pressure-supply loss, Engine 2 power loss and local Yellow engine-driven pump
loss. Engine 2 power loss predicts both generator and Yellow pump output loss, so a
single engine failure and two separate local failures are different explanations of the
same symptoms. Engine core speed and fuel flow tell them apart.

Each candidate shows **model checks matched**, for example `7/7 checks`. This is the
fraction of the candidate's predictions that the observations confirm. It is a measure
of evidence coverage, **not** the probability that the candidate is the cause. Two
competing explanations can both reach 7/7.

## Run the recorded demo

From the repository root, with **Python 3.11 or later** and no extra packages:

```sh
python -B -m aircraft_debugger.sim_panel --replay results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --port 8769
```

Open [the local evidence inspector](http://127.0.0.1:8769). Move from sample **17**
through **22** to watch the candidate set change as hydraulic evidence arrives. Expand
both compatible explanations, then advance to the end to compare recovered readings
with the incident history.

To investigate the Engine 2 cascade instead:

```sh
python -B -m aircraft_debugger.sim_panel --investigate --replay results/engine-drive-20261106-01/engine-auto/observations.jsonl --port 8769
```

Advance to the last sample. The inspector shows which observations support the shared
Engine 2 power-loss path, which local failures could be masked, and the conflicts that
appear when Engine 2 power loss is excluded. Add `--pilot` for the concise view. This
capture starts airborne, so the pilot view has no ground-power clock origin and shows
`--:--:--` timestamps.

To write an inspectable diagnosis report:

```sh
python -B -m aircraft_debugger.diagnosis --observations results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --mode temporal --output work/paired-replay
```

Run the test suite:

```sh
python -B -m unittest discover -s tests -v
```

## What the experiments showed

![Generator 2 output and Blue hydraulic pressure fall while bus voltage and indicated quantity are retained](docs/figures/pressure-pair-observed.png)

In this recorded airborne run, Generator 2 output dropped to zero while the monitored
buses stayed near **115 V**, because another source picked up the load. Blue hydraulic
pressure fell from **3,000 psi** to zero while the reservoir indication stayed at
**8 raw model units**, which points to a pressure-supply fault rather than fluid loss. Both
"two independent faults" and "one shared event" fit these observations, and AeroTrace
reports both. [Recording, diagnosis and operator evidence](results/pressure-pair-20261106-01/RESULT.md)

| Check | Result |
| --- | --- |
| **Prospective evaluation** | All **6** planned episodes matched their sealed expected candidate sets across **2** fresh simulator flights (276 complete polls). The expected sets were fixed before each flight. |
| **Live vs. replay** | Live and offline results agreed on candidate sets, evidence and observed impact for all six episodes. |
| **Engine 2 drive-loss study** | All **4** planned contrasts matched. Fuel flow and core speed separated an engine loss from separate generator and pump failures. |
| **Timed study** | A staggered generator-then-pump intervention ruled out a shared trigger within the declared response limits. Near-simultaneous effects left both explanations open. |
| **Five-fault sequence study** | 1,081 onset histories across all mechanism sets. The expected history was retained in every synthetic case. |
| **v1.3 investigation** | All 444 counterfactual answers agreed with the executable model. The true mechanism set was retained in 10 of 12 cases; the 2 misses are an inconsistent test fixture and a deliberately unmodelled fault. |
| **Update cost** | 95th-percentile live update of **80 ms** over a 1,200-poll session (was 490 ms before context reuse). |
| **Software** | **230** automated tests, run by CI on Linux and Windows with Python 3.11 and 3.13. |

[Engine drive results](results/engine-drive-20261106-01/REPORT.md) · [Prospective evaluation](results/pressure-v2-prospective-20261106-01/REPORT.md) · [Timed fault study](docs/TEMPORAL-STUDY.md) · [Five-fault sequences](docs/FAULT-SEQUENCE-STUDY.md) · [Quantity stress test](results/quantity-indication-stress-20261106-01/README.md) · [Load measurements](results/pressure-v2-load-optimized-20261106-01/REPORT.md) · [Release review](results/v1.3-release-review-20261107-01/REPORT.md) · [Initial validation report (PDF)](output/pdf/AeroTrace-Engineering-Report.pdf)

## Limitations

- **Hidden common causes are not yet detected reliably.** The common-origin screen
  groups effects whose onsets fall within a 3-simulator-second window. In the
  v1.3 comparison it raised a possible shared origin on both independent control
  cases whose faults began close together (2 of 6 independent controls overall).
  Timing alone cannot separate one physical event from coincident independent faults,
  and the telemetry has no channel that observes physical damage.
  [Details](results/v1.3-investigation-20261107-01/REPORT.md)
- **Small, hand-built model.** Five mechanism classes and their dependency graph were
  written by the developer from the simulator's source files. The model has no failure
  probabilities, so it cannot rank equally compatible explanations.
- **Agreement with expected sets is not accuracy on real aircraft.** The expected sets
  come from the same model and the same developer. The evaluation checks that the
  software does what it was specified to do under the tested simulator conditions.
- **Narrow operating envelope.** Steady level flight in one simulated aircraft. Climb,
  descent, approach and other aircraft are untested.

## Related work

AeroTrace is a small instance of **consistency-based (model-based) diagnosis**: a
system model predicts behaviour, and a diagnosis is a set of faulty components that
makes the predictions consistent with the observations.

- R. Reiter, "A theory of diagnosis from first principles," *Artificial Intelligence*, 32(1), 57–95, 1987.
- J. de Kleer and B. C. Williams, "Diagnosing multiple faults," *Artificial Intelligence*, 32(1), 97–130, 1987.
- R. Isermann, *Fault-Diagnosis Systems: An Introduction from Fault Detection to Fault Tolerance*, Springer, 2006.

Unlike probabilistic approaches such as Bayesian networks, AeroTrace does not assign
prior failure rates; it keeps every consistent explanation. A comparison against a
probabilistic baseline is a natural next step.

## Project map

| Path | Contents |
| --- | --- |
| [aircraft_debugger/](aircraft_debugger/) | Telemetry validation, evidence extraction, causal models, live and replay panels |
| [configs/](configs/) | Aircraft setup, fault mappings, qualification rules and pinned simulator assets |
| [results/](results/) | Observation streams, expected profiles, saved diagnoses and experiment provenance |
| [tests/](tests/) | Automated checks and regressions using recorded observations |
| [docs/](docs/) | Engineering report, architecture, reproduction and simulator setup |

## License

Original AeroTrace work is licensed under the [MIT License](LICENSE).
Copyright 2026 Harsh Thakur.

Archived FlightGear A320-family model source keeps its GNU General Public License
version 2 terms. See [third-party notices](THIRD_PARTY_NOTICES.md) for the covered
files, original copyright statements and license text.

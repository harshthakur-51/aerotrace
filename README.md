# AeroTrace

**An evidence-driven debugger for cross-system failures in an Airbus A320 simulation.**

AeroTrace reads FlightGear telemetry and explains which causal configurations fit the observed propulsion, electrical and hydraulic effects. It shows the evidence, contradictions and missing measurements for each candidate, and keeps competing explanations visible when the signals cannot distinguish them.

[Engineering report (PDF)](output/pdf/AeroTrace-Engineering-Report.pdf) · [Architecture](docs/ARCHITECTURE.md) · [Reproduce the results](docs/REPRODUCING.md) · [Connect FlightGear](docs/LIVE-SIMULATOR.md)

## Open the v1.2 pilot view

From the repository root with Python 3.11 or later, run the Engine 2 example using the included recording.

```sh
python -B -m aircraft_debugger.sim_panel --pilot --replay results/engine-drive-20261106-01/engine-auto/observations.jsonl --port 8769
```

Open [the local pilot view](http://127.0.0.1:8769) and advance to the last sample. The display groups the recorded events under the shared Engine 2 power-loss explanation using A320 component abbreviations. It shows compatible and unconfirmed histories as C:U and gives an evidence support percentage for each displayed explanation. This archived flight begins airborne, so the ground-power timestamps show `--:--:--`. [Pilot view and sequence study](docs/FAULT-SEQUENCE-STUDY.md#pilot-output)

## What the experiments showed

![Generator 2 output and Blue hydraulic pressure fall while bus voltage and indicated quantity are retained](docs/figures/pressure-pair-observed.png)

The figure shows a recorded airborne A320 simulation. Generator 2 output reached zero while the monitored buses stayed near **115 volts**. Blue hydraulic pressure fell from **3,000 psi** (pounds per square inch) to zero while the reservoir indication stayed at **8 raw model units**. Both the independent-fault and shared-event configurations fit those observations. [Recording, diagnosis and operator evidence](results/pressure-pair-20261106-01/RESULT.md)

| Check | Result |
| --- | --- |
| **Prospective version 2 evaluation** | All **6** planned episodes matched their sealed candidate sets across **2** fresh simulator flights. All **276** public polls were complete. |
| **Live and recorded diagnosis** | The final live and replay results agreed for all six episodes, including the candidate sets, evidence and observed impact. |
| **Timed airborne study** | A staggered generator and pump intervention ruled out a shared trigger within the declared response limits. Near-synchronous effects left both explanations compatible. Recovery between interventions produced two separate incidents. |
| **Engine 2 drive-loss study** | All **4** planned contrasts matched their expected candidates. Generator and Yellow pump outputs fell in both failure patterns. Fuel flow and core speed distinguished the engine loss from the separate source failures. |
| **Five-fault sequence study** | The offline debugger tests **1,081** onset histories across **26** multi-fault sets and five isolated mechanisms using the same dependency graph. The software exercise retained the expected history in every synthetic case. Native replays show where timing narrows the order and where faults stay masked. |
| **Local update cost** | After airborne context reuse, the 95th-percentile update was **80 ms** over a synthetic 1,200-poll fixture, compared with **490 ms** before. Host background load differed between runs. These times cover local processing and snapshot copying. |
| **Software verification** | **220** automated tests cover the observation contract, causal inference, pilot display, replay, evaluation and operator controls. |

[Engine drive results](results/engine-drive-20261106-01/REPORT.md) · [Prospective evaluation](results/pressure-v2-prospective-20261106-01/REPORT.md) · [Timed fault study](docs/TEMPORAL-STUDY.md) · [Quantity stress test](results/quantity-indication-stress-20261106-01/README.md) · [Load measurements](results/pressure-v2-load-optimized-20261106-01/REPORT.md)

## Run the recorded demo

From the repository root, with **Python 3.11 or later**:

```sh
python -B -m aircraft_debugger.sim_panel --replay results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --port 8769
```

Open [the local evidence inspector](http://127.0.0.1:8769). Move from sample **17** through sample **22** to see how the candidate set changes as the hydraulic evidence arrives. Expand both compatible explanations, then advance to the end to compare recovered readings with the incident history. Recorded mode uses only Python and the included data.

Each candidate shows an **evidence support percentage** with the number of model checks behind it. Both explanations in the recorded demo reach 100% while the initiating cause remains ambiguous.

The [version 3 drive-loss replay](docs/ENGINE-DRIVE-STUDY.md#replay-and-compare) compares Engine 2 power loss with a generator and pump pair. It shows the measured alternate supply and explains why Yellow line pressure can persist after the engine-driven pump stops.

The [five-fault sequence replay](docs/FAULT-SEQUENCE-STUDY.md) explains which mechanism sets and onset orders fit a public recording, including why timing or observed effects exclude an order. The separate operator planner produces onset and release designs for future collection.

To write an inspectable diagnosis report, run the following command with an unused output directory:

```sh
python -B -m aircraft_debugger.diagnosis --observations results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --mode temporal --output work/paired-replay
```

Run the full test suite from the same folder:

```sh
python -B -m unittest discover -s tests -v
```

## What the debugger can explain

The model tracks generator output, bus voltage, indicated Blue reservoir quantity and Blue pressure. It evaluates supported causal configurations against those measurements and distinguishes absent, observed and unknown effects. Version 1 covers generator source loss and hydraulic inventory loss. Version 2 adds Blue pressure-supply loss. Version 3 adds propulsion and Yellow supply observations, with 13 candidate configurations across five mechanism classes.

The simulator operator records fault commands and readiness checks separately. Diagnosis uses the public observations. The evaluator compares a completed prediction with the expected candidate set declared before the flight. The replay also preserves incident history after the current measurements recover.

The evaluations measure agreement with predeclared candidate sets at selected conditions in the FlightGear A320 model. The observed signals leave component identity, common physical damage and broader aircraft capability unresolved. The live inspector exposes its 1,200-poll inference limit.

## Project map

| Path | Contents |
| --- | --- |
| [aircraft_debugger/](aircraft_debugger/) | Telemetry validation, evidence extraction, causal models, live and replay panels |
| [configs/](configs/) | Aircraft setup, fault mappings, qualification rules and pinned simulator assets |
| [results/](results/) | Observation streams, expected profiles, saved diagnoses and experiment provenance |
| [tests/](tests/) | Automated checks and regressions using recorded observations |
| [docs/](docs/) | Engineering report, architecture, reproduction and simulator setup |

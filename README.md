# AeroTrace

**An evidence-driven debugger for cross-system failures in an Airbus A320 simulation.**

AeroTrace reads FlightGear telemetry and explains which causal configurations fit the observed electrical and hydraulic effects. It shows the evidence, contradictions and missing measurements for each candidate, and keeps competing explanations visible when the signals cannot distinguish them.

[Engineering report (PDF)](output/pdf/AeroTrace-Engineering-Report.pdf) · [Architecture](docs/ARCHITECTURE.md) · [Reproduce the results](docs/REPRODUCING.md) · [Connect FlightGear](docs/LIVE-SIMULATOR.md)

## What the experiments showed

![Generator 2 output and Blue hydraulic pressure fall while bus voltage and indicated quantity are retained](docs/figures/pressure-pair-observed.png)

The figure shows a recorded airborne A320 simulation. Generator 2 output reached zero while the monitored buses stayed near **115 volts**. Blue hydraulic pressure fell from **3,000 psi** (pounds per square inch) to zero while the reservoir indication stayed at **8 raw model units**. Both the independent-fault and shared-event configurations fit those observations. [Recording, diagnosis and operator evidence](results/pressure-pair-20261106-01/RESULT.md)

| Check | Result |
| --- | --- |
| **Prospective version 2 evaluation** | All **6** planned episodes matched their sealed candidate sets across **2** fresh simulator flights. All **276** public polls were complete. |
| **Live and recorded diagnosis** | The final live and replay results agreed for all six episodes, including the candidate sets, evidence and observed impact. |
| **Timing comparison** | The timing rule changed no candidate sets on the native evaluation recordings. In replay stress tests, it rejected a late false quantity decline. An early false decline could still make the inventory-loss explanation fit. |
| **Local update cost** | After airborne context reuse, the 95th-percentile update was **80 ms** over a synthetic 1,200-poll fixture, compared with **490 ms** before. Host background load differed between runs. These times cover local processing and snapshot copying. |
| **Software verification** | **190** automated tests cover the observation contract, causal inference, replay, evaluation and operator controls. |

[Prospective evaluation](results/pressure-v2-prospective-20261106-01/REPORT.md) · [Quantity stress test](results/quantity-indication-stress-20261106-01/README.md) · [Load measurements](results/pressure-v2-load-optimized-20261106-01/REPORT.md)

## Run the recorded demo

From the repository root, with **Python 3.11 or later**:

```sh
python -B -m aircraft_debugger.sim_panel --replay results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --port 8769
```

Open [the local evidence inspector](http://127.0.0.1:8769). Move from sample **17** through sample **22** to see how the candidate set changes as the hydraulic evidence arrives. Expand both compatible explanations, then advance to the end to compare recovered readings with the incident history. Recorded mode uses only Python and the included data.

To write an inspectable diagnosis report, run the following command with an unused output directory:

```sh
python -B -m aircraft_debugger.diagnosis --observations results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --mode temporal --output work/paired-replay
```

Run the full test suite from the same folder:

```sh
python -B -m unittest discover -s tests -v
```

## What the debugger can explain

The model tracks generator output, bus voltage, indicated Blue reservoir quantity and Blue pressure. It evaluates supported causal configurations against those measurements and distinguishes absent, observed and unknown effects. Version 1 covers generator source loss and hydraulic inventory loss. Version 2 adds pressure-supply loss, which can explain lost pressure with a steady quantity indication.

The simulator operator records fault commands and readiness checks separately. Diagnosis uses the public observations. The evaluator compares a completed prediction with the expected candidate set declared before the flight. The replay also preserves incident history after the current measurements recover.

The evaluation covers selected conditions in the FlightGear A320 model. The observed signals leave component identity, common physical damage and broader aircraft capability unresolved. The six cases measure agreement with predeclared candidate sets. The live inspector exposes its 1,200-poll inference limit.

## Project map

| Path | Contents |
| --- | --- |
| [aircraft_debugger/](aircraft_debugger/) | Telemetry validation, evidence extraction, causal models, live and replay panels |
| [configs/](configs/) | Aircraft setup, fault mappings, qualification rules and pinned simulator assets |
| [results/](results/) | Observation streams, expected profiles, saved diagnoses and experiment provenance |
| [tests/](tests/) | Automated checks and regressions using recorded observations |
| [docs/](docs/) | Engineering report, architecture, reproduction and simulator setup |

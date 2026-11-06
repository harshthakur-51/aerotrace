# Engine 2 drive-loss diagnosis

An Engine 2 power loss can remove generator 2 output and the Yellow engine-driven pump (EDP) together. Two separate source failures can produce the same outputs while the engine keeps running. This study tests both explanations with hydraulic backup available and inhibited. A Yellow pressure reading alone cannot identify the initiating failure. [Declared contrasts](../results/engine-drive-20261106-01/PROTOCOL.md) · [Results](../results/engine-drive-20261106-01/REPORT.md)

## Native model and measurements

The pinned FlightGear A320-200-CFM model drives the generator and Yellow EDP from Engine 2 core speed. The power transfer unit (PTU) can use pressure from Green to support Yellow, and an electric pump is another alternate source. The independent pair uses the native generator and pump failure flags. The propulsion intervention uses the native fuel cutoff input to let the engine lose power and spool down. The case represents functional power loss. It leaves initiating damage, fire and debris unverified.

| Added observation | What it measures in this study |
| --- | --- |
| Engine 2 core speed (N2) | High-pressure spool speed in percent of the simulator reference. |
| Engine 2 fuel flow | Indicated flow in pounds per hour (lb/h). |
| Yellow EDP, electric pump and Green-to-Yellow transfer outputs | Separate modeled pressure outputs in pounds per square inch (psi). These model properties provide more detail than ordinary cockpit pressure indications. |
| Yellow line pressure | Resulting circuit pressure in psi. |
| Yellow reservoir quantity | Indicated raw model units. |
| PTU selection | The observed cockpit selector, automatic or off. The diagnostic branch uses measured transfer output. |

The public profile contains 28 channels including the previous 20. Operator fault flags, cutoff input, phase labels and expected answers are separate from the public stream. The engine-drive checks require observations of the pinned A320 airborne. The model expects low fuel flow and low N2 for the sustained cutoff-like pattern. In the separate-source hypothesis, both engine observations should remain above their low thresholds.

The Yellow EDP edge to line pressure is conditional. The debugger checks whether the source and line readings are close in time and whether the measured supply condition persists for six simulator seconds. It then checks whether the line retains pressure with adequate alternate output or loses it when both alternate outputs are low. An intermediate line pressure, low indicated quantity or inadequate sampling can leave this check unresolved. The pressure thresholds, duration and evidence scoring are project rules for this tested operating regime. [Feature implementation](../aircraft_debugger/propulsion_features.py) · [Hypothesis graph](../aircraft_debugger/hypotheses.py)

The Bureau d’Enquêtes et d’Analyses pour la sécurité de l’aviation civile (BEA) identifies the Yellow circuit’s Engine 2 pump and Green–Yellow transfer in section 2.1. It also describes cases where windmilling can still provide hydraulic drive. The National Transportation Safety Board (NTSB) describes separate pump and system indications in sections 4.3 and 4.3.1 of its factual report. These sources support the topology. The source, pressure and timing values here come from the pinned model and recorded runs. [BEA CS-TKP, section 2.1](https://bea.aero/fileadmin/uploads/tx_elydbrapports/cs-p140425.en.pdf) · [NTSB DCA12IA096, sections 4.3 and 4.3.1](https://data.ntsb.gov/Docket/Document/docBLOB?FileExtension=.PDF&FileName=Operations+2+-+Factual+Report+of++Operations%2FHuman+Performance+Group+Chairmen-Master.PDF&ID=40384276)

## Replay and compare

```powershell
python -B -m aircraft_debugger.sim_panel --model v3 --replay results/engine-drive-20261106-01/engine-off/observations.jsonl --port 8772
```

At [the local panel](http://127.0.0.1:8772), move to the end of the recording. Expand **Engine 2 power loss** to see the graph paths, pressure consequence check and supported-check count. Use the `engine-auto` recording to inspect the same power loss with transfer available. The version 3 catalogue includes 13 candidate configurations across five mechanism classes. Engine drive plus an additional Blue pressure loss is representable as either a shared or independent history. The two explanations remain tied under this observation model.

```powershell
python -B -m aircraft_debugger.diagnosis --model v3 --observations results/engine-drive-20261106-01/engine-off/observations.jsonl --output work/engine-off-prediction
python -B -m aircraft_debugger.propulsion_study --study results/engine-drive-20261106-01 --output work/engine-study-replay
```

The comparison reruns the same public observations with engine measurements withheld and with alternate pressure measurements withheld. It evaluates the final candidate sets against separately declared targets and records observed onset intervals. The four episodes use two flights at one target condition, with the separate-source recipe preceding the engine cutoff in each flight. Accuracy here refers to candidate agreement in those controlled contrasts. Evidence percentages describe supported checks. Field accuracy and probability calibration would require independent data.

The first two recordings were diagnosed after collection. The second two also ran the version 3 inspector during collection. Each captured final live verdict agreed with replay. All four episodes matched the declared candidate, and the measurements withheld in the ablations changed the results as expected. [Comparison with measured values](../results/engine-drive-20261106-01/REPORT.md)

The earlier engine-auto operator archive gained an imported analysis dependency reconstructed from the recorded edit history. The supplement carries a separate digest. The study computes its predictions from the original public stream with a separately identified inference version. [Archive supplement](../results/engine-drive-20261106-01/engine-auto/private_truth/source-supplement.json)

## Controlled collection

The existing airborne controller supports `engine_2_cutoff` and `independent_generator_2_and_yellow_edp` with the declared `--ptu auto` or `--ptu off` setting. The controller reads the selector and verifies a fresh stable reference before injection. Configuration and native fault controls remain separate. An example is shown for a prepared and authorized simulator session.

```powershell
python -B -m aircraft_debugger.airborne_experiment --case engine_2_cutoff --ptu off --output work/engine-drive-new --config results/pressure-v2-protocol-20261106-01/qualification-B.json --active-seconds 28 --recovery-seconds 10 --live-panel-port 8768 --diagnostic-model v3
```

The collection tail measures what happens after the cutoff input is released. Engine relight and power restoration depend on the simulator state and are checked through observed data.

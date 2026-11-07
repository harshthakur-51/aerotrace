# Active causal investigation

AeroTrace v1.3 investigates the surviving explanations from the temporal v4
model. Its inputs are validated public telemetry and explicitly supplied
response bounds. Fault commands, labels and operator journals are confined to
experiment collection and post-replay evaluation.

## Run the flagship replay

From the repository root, extract the five existing synthetic development cases
to a fresh folder. The bundle contains their original observation bytes, bounds
and a separate evaluation design file. The commands below read only the public
observations and the shared response bounds.

```powershell
Expand-Archive -LiteralPath results/v1.3-investigation-20261107-01/development-fixtures.zip -DestinationPath work/v13-dev-fixtures
python -B -m aircraft_debugger.sequence_reasoning --observations work/v13-dev-fixtures/05/observations.jsonl --response-bounds work/v13-dev-fixtures/response-bounds.json --only generator_2_source_path_fault --output work/case05-investigation
python -B -m aircraft_debugger.sim_panel --investigate --replay work/v13-dev-fixtures/05/observations.jsonl --response-bounds work/v13-dev-fixtures/response-bounds.json --port 8769
```

Move the replay slider to the final sample. The detailed inspector exposes
observed effects, surviving sets, masked mechanisms, the comparison of
simulated measurement outcomes, and exclusions. The sequence command writes the
same investigation to `report.json` and its concise view to `report.md`.
Add `--pilot` to the panel for the concise view, or omit `--replay` to attach
the inspector to the live A320. [Local inspector](http://127.0.0.1:8769)

In Case 05 the generator-only query fails against measured Yellow pump output,
Yellow line pressure, Blue quantity and Blue pressure. A set containing local
Generator 2 and Yellow pump supply losses plus Blue inventory loss survives.
Adding a Blue pressure-supply mechanism still fits. At the first Blue pressure
degradation the pressure reading was 2,400 pounds per square inch and indicated
quantity was 7 raw model units against an earlier reference of 8. The
inventory-first path is temporally consistent, and the model has no quantity
threshold that separates it from an additional supply loss. The close group of
cross-system changes also fits distinct local paths. Its initiating origin
remains unknown.

## How the investigation works

**Counterfactuals.** `--only`, `--require` and `--exclude` constrain the
same fitted catalogue. Flags may repeat to define a set. An exact query tests
that set alone. An exclusion query tests every set without the specified
mechanism. The answer distinguishes compatible, unconfirmed and excluded
matches and includes the original dependency conflicts and examples of
failed timing constraints. It makes no simulator calls.

**Passive measurements.** Each unresolved modelled effect has two conclusive
outcomes. A candidate survives each outcome allowed by its dependency paths.
A conditional consequence survives both branches. An unknown result retains
all current candidates. Ranking minimizes the number of sets left in the
larger conclusive branch, then in the smaller branch, then uses the effect
identifier for a stable order. Minimum elimination is the number of starting
sets minus the larger branch size. These dimensionless counts are a project
metric defined in [the selection implementation](../aircraft_debugger/investigation.py).
No priors enter the calculation.

The selected channels must be usable in the latest public observation and
have coverage of the relevant window. Pending coverage may need additional
qualified polls. Unavailable channels and historical gaps appear as separate
discriminators, with no passive recommendation to obtain them from the
current capture. A fresh reading cannot reconstruct an earlier gap. The
partition compares effect presence over an incident and leaves detailed onset
ordering to the timing solver. Case 04 shows why either incident-time Engine 2
core speed (N2) or fuel flow matters. A conclusive result would leave either
four engine-containing sets or one separate-source set. Both channels are
missing in that replay.

**Masking.** Each surviving set lists the observed effects and unknown required
effects along its paths. An exclusive first-effect path or retained-drive
witness supports the associated mechanism within that set. A strict subset
that fits without a root shows why an additional mechanism can remain possible.
A separate downstream analysis identifies conditional consequences. The
existing settled Yellow supply check can positively witness measured backup
retaining Yellow line pressure while the engine-driven pump is degraded.

**Common origin.** The screen uses a provisional three simulator second span of
first observed effects with qualified onset brackets. A conditional downstream
effect is omitted from this screen when an earlier, separated observed effect
can already account for it in a minimal surviving set. The timing solver then
tests whether one existing root can account for a group and whether an onset
group of multiple roots could explain it. A shared root is a model explanation.
A common onset group with several roots can also represent coincidence.
Physical attribution would need independent upstream, exposure or
component-local evidence. The current graph contains no physical exposure
model. The screen also retains failed checks when no set explains the
observations jointly. The screening span has no external physical validation.
[Screen implementation](../aircraft_debugger/common_cause.py)

The common-cause possibility flag records a hypothesis surfaced by this screen.
An unset flag leaves initiating events beyond the model unassessed. The physical
initiator remains unknown in either case.

The pilot view uses A320 component labels and separates observed events,
possible explanations and what to investigate next. C:U counts compatible
and unconfirmed histories across the catalogue. Model-check support describes
matched checks for a displayed explanation and carries no estimate of cause
likelihood. Time since ground power is shown when its transition was recorded.
The tool remains an experimental simulator debugger.

## Reproduce the comparison

The evaluator runs the released v1.2 checkout and the current code in separate
Python processes on the same observation bytes and bounds. It checks the
original fit, including each history and exclusion. It benchmarks inference on
preloaded rows and records the observed outcomes of separately restoring
withheld channels. Its synthetic profiles and operator truth are separate from
the diagnostic inputs. [Protocol](../configs/investigation-evaluation.json)

```powershell
git clone https://github.com/harshthakur-51/aerotrace.git work/v12-reference
git -C work/v12-reference checkout --detach 9101b111de790c50ac0af777d01c99284d88d43e
python -B scripts/evaluate_investigation.py --baseline-checkout work/v12-reference --development-dir work/v13-dev-fixtures --output work/v13-comparison
```

[Measured results and limitations](../results/v1.3-investigation-20261107-01/REPORT.md)

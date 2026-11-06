# Sealed bounded-profile evaluation

Implemented 3 November 2026. This evaluator checks a finite diagnostic specification;
it does not measure unique physical cause accuracy or pilot benefit. It consumes
private targets only after prediction and never invokes the diagnostic engine.

## What is sealed

A new protocol directory stores the exact model, detector thresholds, inference
source hashes, scorer hash, known development run hashes and declared flight groups.
Both raw-file and canonical public-observation hashes exclude reuse of known data;
reformatting JSON cannot make a development run new. Existing files with invalid old
schemas cannot enter prediction and are separately noted in the development inventory.
Planned evaluation run IDs, flight groups and expected profiles are fixed before data
collection. A profile cannot be selected afterward just to match the result.

```powershell
.\.venv\Scripts\python.exe -B -m aircraft_debugger.evaluation seal --development-runs work/development-runs.json --planned-final-runs work/planned-runs.json --output work/protocol-NEW
```

The development registry is an explicit JSON list of objects with `run_id`,
`flight_group` and `observations` (public-file path). Planned runs contain `run_id`,
`flight_group` and `profile`. Entire flights/groups stay on one side of the split.
Grouping is an operator declaration; hashes and labels cannot prove independence.
The seal is an integrity record, not an authenticated or tamper-proof execution system.

## Predict first, score second

Use the normal diagnosis CLI with one explicit whole public file. Only after that
command completes may the evaluator consume its separate target file:

```powershell
.\.venv\Scripts\python.exe -B -m aircraft_debugger.evaluation score --protocol work/protocol-NEW --prediction work/prediction-NEW --observations results/NEW/observations.jsonl --target work/target.json --output work/score-NEW.json
```

Target fields are `schema_version` (integer 1), `run_id`, `flight_group`,
`observation_sha256`, `canonical_observations_sha256`, `profile` and `data_role`
(`development` or `final`). Scoring verifies the observations, prediction artifacts,
executed source archive, model and sealed inference/scorer hashes. It refuses known
training/development data or flight groups as final, undeclared final assignments,
source/model drift, changed artifacts and existing output. Changed sources require
a new protocol and genuinely new final data, not tuning on the observed results.

| Bounded profile | Expected compatible configurations |
|---|---|
| `reference` | selected reference |
| `source_path` | generator-2 source-path configuration |
| `blue_inventory` | blue inventory-loss configuration |
| `joint_selected_effects` | BOTH independent pair and grouped joint event |

A source-path match is unique only inside this catalogue; it does not establish a
specific failed component. The joint target deliberately requires both equivalent
histories. No unique debris/common-origin truth is manufactured from recipe labels.
These expected sets and the exact-match criterion are project-authored specification
checks, with implementation provenance in `aircraft_debugger/evaluation.py`; no
external physical validation is claimed.

Each run reports expected/observed/plausible configurations, missing/extra compatible
IDs, data sufficiency, model fit, current versus incident impact and a bounded-profile
match. Insufficient observations remain a separate, retained result with a null match;
never silently exclude them or turn them into healthy or successful diagnoses.
Collection/prediction failures must stay listed in the cohort summary, even when
there is no score file. Do not report prefixes as independent trials.

## Prospective pilot versus final project claims

A first prospective cohort can test the locked workflow on a fresh simulator flight
using reference, isolated source, isolated inventory and joint cases. Four episodes
on one flight are still one declared flight group under one operating condition.
That is a bounded specification/acceptance pilot, not broad causal accuracy,
statistical independence or completed real-aircraft validation. The `final` role
means held out for that sealed protocol; it does not declare the entire project
ready for final submission. Publish limitations, mismatch/insufficient/failed runs
and method-ablation results alongside matches.

## Explicit version 2 seal

Use `seal --model v2` to bind the three-mechanism catalogue and the temporal
prediction method. Predict with `diagnosis --model v2 --mode temporal`. The
version 2 protocol accepts the four existing profiles and the following two:

| Bounded profile | Expected compatible configurations |
|---|---|
| `pressure_supply` | Blue pressure-supply-path configuration |
| `joint_pressure_effects` | Both independent and grouped pressure-pair configurations |

The version 2 seal checks the prediction method in addition to the model and
source hashes. Use the archived scorer and archived inference source for the
historical version 1 pilot. New prospective data need a new seal.

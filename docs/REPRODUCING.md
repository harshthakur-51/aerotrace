# Reproduce the results

Run these commands from the repository root with Python 3.11 or later. The recorded workflows use the standard library and the included data.

## Inspect the native paired recording

```sh
python -B -m aircraft_debugger.sim_panel --replay results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --port 8769
```

At [127.0.0.1:8769](http://127.0.0.1:8769), select sample 22 or later. The two compatible pressure-pair configurations are visible in the causal inspector. The final sample retains the incident after the measurements recover.

## Reproduce a sealed prospective score

Predict from one included public observation file, then compare the prediction against the separately archived expected candidate set. Use fresh output paths for each run.

```sh
python -B -m aircraft_debugger.diagnosis --model v2 --mode temporal --observations results/pressure-v2-prospective-20261106-01/episode-B-03/observations.jsonl --output work/episode-B-03-prediction
python -B -m aircraft_debugger.evaluation score --protocol results/pressure-v2-protocol-20261106-01/sealed --prediction work/episode-B-03-prediction --observations results/pressure-v2-prospective-20261106-01/episode-B-03/observations.jsonl --target results/pressure-v2-prospective-20261106-01/private_truth/episode-B-03/target.json --output work/episode-B-03-score.json
```

The expected score is `matched_bounded_profile`, with both independent and grouped pressure-pair candidates. [Saved score](../results/pressure-v2-prospective-20261106-01/episode-B-03/score.json) · [Evaluation report](../results/pressure-v2-prospective-20261106-01/REPORT.md)

## Verify the software

```sh
python -B -m unittest discover -s tests -v
```

The native simulator setup is separate from the replay and automated checks. [Live setup](LIVE-SIMULATOR.md)

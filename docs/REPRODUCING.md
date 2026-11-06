# Reproduce the results

Run these commands from the repository root with Python 3.11 or later. The recorded workflows use the standard library and the included data.

## Compare onset orders in the pilot view

```sh
python -B -m aircraft_debugger.sequence_reasoning --observations results/timed-pair-20261106-01/observations.jsonl --response-bounds configs/sequence-pair-response-bounds.json --output work/v1.2-staggered-replay
```

The terminal and `report.md` show the v1.2 pilot display. The JSON report records the effect brackets and compatibility decision for all 1,081 histories plus the reference. For the local Generator 2 and Blue pump pair, generator-first is the sole order that fits the declared response limits. This capture leaves propulsion alternatives unconfirmed. [Sequence study](FAULT-SEQUENCE-STUDY.md)

## Inspect the native paired recording

```sh
python -B -m aircraft_debugger.sim_panel --replay results/pressure-pair-20261106-01/pair/observations.jsonl --model v2 --port 8769
```

At [127.0.0.1:8769](http://127.0.0.1:8769), select sample 22 or later. The two compatible pressure-pair configurations are visible in the causal inspector. The final sample retains the incident after the measurements recover.

## Reproduce the Engine 2 drive contrast

Version 3 adds an observation profile for engine drive and Yellow hydraulic backup. The [drive-loss study](ENGINE-DRIVE-STUDY.md) shows how to replay the engine-loss and paired-failure recordings and regenerate the measurement-ablation results.

## Reproduce a sealed prospective score

Run the source included with the seal to reproduce the exact version 2 hashes. The version 3 extension shares parts of the active inference implementation, and the seal checks the executed bytes. Use fresh output paths for each run.

```powershell
$replayRoot = (Get-Location).Path
$replaySeal = Join-Path $replayRoot 'results/pressure-v2-protocol-20261106-01/sealed'
$replayCohort = Join-Path $replayRoot 'results/pressure-v2-prospective-20261106-01'
$replayObservations = Join-Path $replayCohort 'episode-B-03/observations.jsonl'
$replayTarget = Join-Path $replayCohort 'private_truth/episode-B-03/target.json'
$replayPrediction = Join-Path $replayRoot 'work/episode-B-03-prediction'
$replayScore = Join-Path $replayRoot 'work/episode-B-03-score.json'
Push-Location (Join-Path $replaySeal 'executed-source')
try {
    python -B -m aircraft_debugger.diagnosis --model v2 --mode temporal --observations $replayObservations --output $replayPrediction
    if ($LASTEXITCODE -ne 0) { throw 'Sealed replay failed' }
    python -B -m aircraft_debugger.evaluation score --protocol $replaySeal --prediction $replayPrediction --observations $replayObservations --target $replayTarget --output $replayScore
    if ($LASTEXITCODE -ne 0) { throw 'Sealed evaluation failed' }
} finally {
    Pop-Location
}
```

The expected score is `matched_bounded_profile`, with both independent and grouped pressure-pair candidates. [Saved score](../results/pressure-v2-prospective-20261106-01/episode-B-03/score.json) · [Evaluation report](../results/pressure-v2-prospective-20261106-01/REPORT.md)

## Verify the software

```sh
python -B -m unittest discover -s tests -v
```

The native simulator setup is separate from the replay and automated checks. [Live setup](LIVE-SIMULATOR.md)

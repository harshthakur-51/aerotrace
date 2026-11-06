# AeroTrace method comparison

Implemented 3 November 2026. This is an executable development ablation, not an
accuracy result or locked final evaluation.

```powershell
.\.venv\Scripts\python.exe -B -m aircraft_debugger.comparison --observations results/airborne-contrast-20261028-01/observations.jsonl results/airborne-contrast-20261029-01/observations.jsonl results/airborne-pairs-20261029-01/grouped-recipe/observations.jsonl --output work/comparison-NEW
```

Pass whole public JSON Lines files; each is analyzed separately and may appear only
once. Output must be new. No manifest, recipe label, sibling private file or native
flag enters inference. The command verifies input/source stability and archives the
executed source, hashes and results. `comparison.md` summarizes whole recordings;
`comparison.json` retains shared prefix facts, impacts and method outcomes, including
candidate contradictions. Prefix counts are explicitly correlated observations.

Use `--model v2` to compare all three methods with the pressure-supply catalogue.
Use `--data-role post_prediction_descriptive` for a comparison performed after
sealed scoring. That role records the analysis purpose.

| Method | Shared input | Added reasoning | Cause output |
|---|---|---|---|
| Alert-only | Same incident facts, quality and declared catalogue | Report observed selected effects | No cause inference; candidate set is null, not every/zero causes |
| Dependency | Same facts and catalogue | Required/conditional graph predictions and contradictions | Compatible/plausible configurations within catalogue |
| Temporal dependency | Same facts and catalogue | Same graph plus qualitative inventory-before-pressure constraint | Same fields, with inconsistent order allowed to reject a configuration |

This alert-only comparator deliberately shares history-aware fact extraction. It
isolates the causal layer's contribution; it is not a separate raw cockpit-alert or
warning-latency benchmark. The atemporal model retains timestamp quality checks and
incident bookkeeping. Removing those would change the observations or scope as well
as temporal constraints and would not be the requested controlled ablation.

For each whole input, the summary lists final candidates/statuses and the samples
where temporal evaluation changed status, compatible candidates or plausible
candidates. Changed support text alone is not counted as changed discrimination.
A zero must be reported honestly. Changes are model-consistency differences, not
physical correctness or cause-identification gains. Pressure preceding inventory is
a useful software counterexample: the represented depletion path can fit static
facts but contradict their order. That fixture is not an additional native fault.

No accuracy, calibrated confidence, time-to-physical-fault-isolation or independent
trial rate is reported. Such measures need separate, defensible evaluation targets,
recording-level splits and private operator truth used only by the evaluator. The
current independent/grouped recipes remain observationally equivalent; scoring one
as the unique physical cause would manufacture a distinction our data cannot make.

The version 1 and version 2 pilots have separate prospectively sealed assignments
and results. Their post-prediction comparisons recorded zero native discrimination
changes from the timing rule. The synthetic quantity stress produced a timing
contradiction in its late-decline variant.
[Version 1 pilot](../results/prospective-pilot-20261103-01/PILOT-REPORT.md) ·
[Version 2 pilot](../results/pressure-v2-prospective-20261106-01/REPORT.md) ·
[Quantity stress](../results/quantity-indication-stress-20261106-01/README.md)

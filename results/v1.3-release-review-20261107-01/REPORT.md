# AeroTrace v1.3 release review

The release review checked source, observation validation, the executable
dependency graph, temporal fitting, investigation, replay and live-session
boundaries, simulator controls, packaging inputs and published claims.
The source parsed under Python 3.11 grammar. The active regression suite
passed all 230 tests again. [Test log](tests.txt)

The exported public tree also passed all 230 tests and the same 110 recording
checks in a fresh Python environment with no third-party packages. Every
executable module matched the active source and the saved v1.3 comparison
hashes. Local documentation links were checked against the public file tree.
[Public-export test log](exported-tests.txt) · [Verification manifest](export-verification.json)

Nine base recordings were replayed through the current code, including four
native captures and the five original stress cases. Additional variants
removed engine-drive, generator, pump, quantity and pressure channels, removed
a poll, and selected the nominal prefixes. All 110 review checks passed.
These are repeated and modified observations from the cited captures.
[Check results](check-results.json) · [Review helper](executed-helper.py)

GEN denotes generator, ENG denotes engine, HYD denotes hydraulic and EDP
denotes engine-driven pump. C and U are compatible and unconfirmed onset
histories. Each surviving mechanism set may have multiple histories.

| Recording | C | U | Surviving sets | Result assessed |
| --- | ---: | ---: | ---: | --- |
| Native ENG 2 loss | 20 | 0 | 4 | Shared engine drive explains GEN and Yellow pump output. Additional local faults remain possible. |
| Native independent GEN/Yellow pair | 3 | 0 | 1 | Retained engine drive requires the local source paths. Physical shared origin remains unresolved. |
| Native isolated Yellow EDP | 1 | 0 | 1 | Local pump path survives with measured alternate hydraulic supply. |
| Fresh independent pair | 3 | 0 | 1 | The latest native control reproduces the local-path distinction. |
| Stress 01 | 42 | 0 | 4 | ENG 2 cascade and independent Blue pressure loss remain separate. |
| Stress 02 | 20 | 0 | 4 | Earlier GEN fault remains required after ENG 2 loses drive. |
| Stress 03 | 3 | 0 | 1 | All five mechanisms survive with three feasible onset histories. |
| Stress 04 | 0 | 87 | 5 | Missing engine-drive observations preserve competing explanations. |
| Stress 05 | 88 | 0 | 2 | An additional masked Blue pressure-supply mechanism remains possible. |

Removing selected channels or a poll preserved every previously surviving
mechanism set in these native samples. Missing channels were never offered
as currently actionable measurements. The four nominal prefixes produced
no abnormal effects and retained the selected reference. Combined required
and excluded roots were also checked in counterfactual queries.

The legacy hydraulic bench entry point also ran. In that illustrative model,
the leak and pressure-sensor-bias cases produced similar measured pressure
while differing in quantity and tracking response. The bench remains
separate from the native A320 evidence.

The review corrected stale public-facing documentation. The front page now
states the current verification count and v1.3 findings, links the current
evaluation first, and labels the earlier PDF as initial native validation.
The architecture and reproduction pages now include active investigation.
The executable source matches the source hashes in the existing v1.3
comparison. Its raw experiments, sealed results and earlier findings remain
available. [v1.3 comparison](../v1.3-investigation-20261107-01/REPORT.md)

The results support release as an experimental debugger for the selected
model. Timing alone still raises unresolved common-origin possibilities on
independent controls. The three simulator second cluster screen is a
provisional heuristic. The numerical support display counts matched model
checks. The data do not measure pilot time savings or validate real-aircraft
diagnosis. Fault masking and compensation are established reasons to expect
observational ambiguity in multiple-fault diagnosis. [NASA technical record](https://ntrs.nasa.gov/citations/20140004901)

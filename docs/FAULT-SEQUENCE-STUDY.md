# Five-fault sequence study

All five selected mechanisms now have isolated airborne recordings.

| Mechanism | Isolated native recording |
| --- | --- |
| Generator 2 source-output loss | [Generator contrast](../results/airborne-contrast-20261028-01/observations.jsonl) |
| Blue hydraulic fluid loss | [Inventory-loss contrast](../results/airborne-contrast-20261029-01/observations.jsonl) |
| Blue electric pump failure | [Pressure-supply contrast](../results/pressure-v2-native-20261103-01/pump-only/observations.jsonl) |
| Engine 2 functional power loss via fuel cutoff | [Engine-drive contrast](../results/engine-drive-20261106-01/engine-auto/observations.jsonl) |
| Yellow engine-driven pump failure | [Pump-only contrast](../results/yellow-edp-isolated-20261106-01/RESULT.md) |

## Generate the private trials

```powershell
python -B -m aircraft_debugger.sequence_plan --output work/private_truth/five-fault-plan.json
```

The generator uses each selected mechanism once. Across the 31 nonempty subsets, it finds 325 strictly ordered selections and 1,081 distinct onset sequences when events can also start in groups. Each sequence with multiple onset groups receives overlapping and clear-gap timing variants. With one timing variant for each single onset group, the default plan contains 2,131 trials. Hold times and spacing are configurable in simulator seconds. [Enumeration code](../aircraft_debugger/sequence_plan.py)

An onset group specifies a planned batch of commands. Real simulator reads and writes have their own timestamps. Releasing an input starts an observation period for recovery. Engine relight, retained flight conditions and permission to enable the next fault require fresh evidence. The generated JSON is an operator design for future collection. The current guarded native runner supports only a subset of the proposed trials. Use the extended public observation profile for compound recordings. Earlier isolated Blue recordings use the older profile.

## Compare onset histories from observations

The same five mechanism rules generate all 26 multi-fault sets, five single-fault
sets and the selected reference. AeroTrace tests all 1,081 nonempty onset histories
against each recording epoch. The inference input is the timestamped public
observations and any explicitly declared response bounds. The test plan,
intervention times and simulator failure flags are separate.

```powershell
python -B -m aircraft_debugger.sequence_reasoning --observations results/timed-pair-20261106-01/observations.jsonl --response-bounds configs/sequence-pair-response-bounds.json --output work/staggered-history-replay
```

Open `report.md` for the measurements and remaining explanations. The JSON report
lists every history, its status, dependency paths, missing evidence and any
contradicting observations or deadlines. The same command works without a
response bounds file. In that mode elapsed response times may be any
nonnegative duration. Timing generally leaves more histories possible.
The version 4 live panel still presents mechanism-set evidence and observed
impact. The order comparison runs offline over a full clock epoch.

| Mechanism | Ground rule used by the model |
| --- | --- |
| Generator 2 source loss | A local source loss reduces measured generator output. Bus voltage can hold if alternate supply is available. |
| Blue fluid loss | Reservoir quantity declines. Pressure can hold while there is enough fluid to sustain supply. |
| Blue pressure-supply loss | The modeled net supply loss reduces line pressure even with quantity retained. The isolated electric-pump intervention exercises this path with the ram air turbine inactive. |
| Engine 2 power loss | In the modeled cutoff episode, fuel flow and core speed fall. Reduced core drive can remove both Generator 2 and the Yellow engine-driven pump outputs. |
| Local Yellow pump loss | Pump output falls with engine drive retained. Electric pump output or hydraulic transfer can maintain line pressure. |

These rules cover the represented fault effects in the pinned FlightGear A320
condition. For example, the pinned Blue electric-pump model requires alternating
current bus 1 in normal airborne operation, so Generator 2 loss alone does not
imply Blue pressure loss. [Executable graph](../aircraft_debugger/hypotheses.py) ·
[Pinned hydraulic model, lines 208–230 and 399–419](https://svn.code.sf.net/p/flightgear/fgaddon/!svn/rvr/20376/branches/release-2024.1/Aircraft/A320-family/Systems/a320-hydraulic.xml#l208) ·
[Yellow hydraulic system description, section 2.1](https://bea.aero/fileadmin/uploads/tx_elydbrapports/cs-p140425.en.pdf)

The retained-drive check requires two consecutive polls of core speed at least 60% and fuel flow at least 100 pounds per hour, with generator output below 5 volts or Yellow pump output below 500 pounds per square inch. Each group of readings must be within 0.25 simulator seconds. These are conservative comparison thresholds for the pinned simulator and match the selected study's drive regime. They are project rules and their accuracy outside this regime is unresolved. [Implementation](../aircraft_debugger/propulsion_features.py)

### How one rule checks every order

1. Follow the graph from each proposed mechanism. Check required effects against
   observed, absent or unknown evidence. Conditional paths allow backup supply
   and other measured conditions to change the downstream outcome.
2. For the first sustained response, bracket the change between the last usable
   nominal reading and first qualifying abnormal reading. Subtract the declared
   maximum delay from the nominal time to get the earliest possible mechanism
   onset for a covered required path. Subtract the minimum delay from the
   abnormal time to get the latest possible onset for that path to explain the
   first response. Timestamps, offsets and inferred bounds are in simulator
   seconds on the same clock epoch. A skipped poll before confirmation, an
   uncovered reference or an undeclared maximum removes the corresponding
   earliest-time constraint. The interval calculation is a project derivation
   that extends the [two-effect timing check](TEMPORAL-STUDY.md).
   [Implementation](../aircraft_debugger/sequence_reasoning.py) ·
   [Timed propagation graphs, section 4](https://arxiv.org/html/1710.03392#S4)
3. Require at least one eligible path to explain each observed effect on time.
   An earlier source can explain the first loss even when a second source fails
   later. If a source is already down with measured engine drive retained,
   require its local path. When pressure clearly drops before inventory in the
   Blue model, require a separate pressure path for the initial drop.
4. Fit a common onset time within a group and strictly increasing times across
   groups. Check the earliest feasible time for each group against the effect
   deadlines. Moving a group later cannot help it meet a missed deadline.
   Keep every order that can satisfy the constraints, including supersets that
   could be masked. A tie in onset time is compatible with multiple physical
   origins. [Implementation](../aircraft_debugger/sequence_reasoning.py)

The report labels an order `compatible` when its dependency checks and timing
can fit, and `unconfirmed` when required observations are unresolved. The
dependency support percentage measures the share of applicable checks backed
by observations. It gives no probability for a physical cause or onset order.

### Verification

The software exercise independently generated a synthetic observation case for
each of the 1,081 onset histories and one for the reference. It varied spacing,
response lag and the presence of conditional effects. The matching history
survived in every case. A unique history remained for 66 fault fixtures and
the reference. The other 1,015 fault fixtures allowed multiple histories under
the modeled measurements. This checks software behavior on a simplified
fixture plant. The simulator evidence comes from nine archived airborne recordings.
[Automated exercise](../tests/test_sequence_reasoning.py) ·
[Verification counts and public input digests](../results/sequence-reasoning-20261106-01/verification.json)

| Airborne recording | What the replay established |
| --- | --- |
| [Isolated Yellow pump](../results/yellow-edp-isolated-20261106-01/RESULT.md) | The local Yellow pump path is the sole compatible history within the model. |
| [Engine 2 drive loss](../results/engine-drive-20261106-01/REPORT.md) | Engine 2 power loss is the smallest explanation. Nineteen other onset histories remain compatible because generator and Yellow pump losses can be masked by the drive loss. |
| [Independent generator and Yellow pump losses](../results/engine-drive-20261106-01/REPORT.md) | Retained drive requires both local source paths. Three onset orders remain compatible without finite response limits. |
| [Staggered generator and Blue pump](../results/timed-pair-20261106-01/timing/report.md) | The local pair retains generator first as its sole possible order with the declared 3-second generator and 10-second Blue pressure maxima. The older capture leaves propulsion alternatives unconfirmed. |
| [Near-synchronous generator and Blue pump](../results/timed-pair-20261106-01/near-synchronous-timing/report.md) | All three orders for the local pair remain possible. Widening the pressure limit to 30 seconds also restores all three on the staggered recording. |

The response bounds are the existing [timed-study assumptions](TEMPORAL-STUDY.md).
Older schema 2 recordings leave the added propulsion measurements unknown. The
history model assumes one sustained onset per selected mechanism per clock epoch
with its required effects observable within the recording. It retains first
responses across recovery gaps. Recovery timing, recurring faults, arbitrary
damage paths and the effects of unmeasured supply modes need separate evidence.
Full native testing of the ordered catalogue remains open.

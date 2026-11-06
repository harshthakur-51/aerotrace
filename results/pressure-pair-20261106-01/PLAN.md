# Airborne generator and pressure-supply contrast

The trial uses a fresh FlightGear 2024.1.7 process with the installed A320-200-CFM
model and the existing qualification settings. The native pilot-input setup requests
10,000 feet and 250 knots. The experiment controller verifies observed readiness and
fifteen advancing simulator seconds of stable flight before applying the two flags.

The prediction comes from the earlier isolated [generator response](../../docs/SESSION-03.md)
and [pump response](../pressure-v2-native-20261103-01/CHECKPOINT-REPORT.md).
With generator 2 and the Blue electric pump failed, generator output should fall,
both alternating current buses should remain supplied, and Blue pressure should fall
while reservoir quantity stays at its reference value of 8 raw model units. A check
of the ram air turbine position before and after the episode records the backup-supply
context. The active window is 24 simulator seconds and the recovery window is 8.

Version 2 temporal diagnosis should retain both the independent and grouped
pressure-pair configurations. Version 1 should report poor model fit. Compare the
live version 2 result with replay of the exact public observations, and verify
clearance of all three supported flags and restoration of the observed quantities.
Record any departure from the predictions. This is a development contrast for the
optional model, with separate private intervention and public observation records.

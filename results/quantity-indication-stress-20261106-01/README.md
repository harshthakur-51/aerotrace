# Reported quantity integrity stress

The two derived recordings replace only the reported Blue quantity values in the
parent pump-only FlightGear record. Both substitute a short stepwise decline
followed by a plateau and restoration to the original value. The early change
begins at sample 17 and the late change at sample 30. Every timestamp, validity
flag and other channel is carried over from the parent. The exact replacements,
parent digest, analysis sources and executed helper are archived.

| Public input | Dependency result | Temporal result |
|---|---|---|
| Original pump-only recording | Pressure-supply configuration | Pressure-supply configuration |
| Early false quantity decline | Inventory-loss configuration | Inventory-loss configuration |
| Late false quantity decline | Inventory-loss configuration | Poor model fit |

All six results matched the predeclared development expectations. The early
substitution passes the same quality and ordering checks as a credible inventory
effect. The late substitution violates the selected inventory-before-pressure
assumption. The example demonstrates the scope of the timing rule and the
dependence of candidate fit on credible measurements. Reported measurements
carry the evidence here, and independent information would be needed to verify
whether the indication reflects physical fluid loss.

These are software transformations of one development recording. They exercise
observation integrity while preserving the original native episode and its
private intervention record. The motivation comes from the distinction between
the Green fluid indication and the later physical examination in Appendix B,
page 218 of the Australian Transport Safety Bureau Qantas 32 report.
[ATSB final report](https://www.atsb.gov.au/sites/default/files/media/4173625/ao-2010-089_final.pdf)

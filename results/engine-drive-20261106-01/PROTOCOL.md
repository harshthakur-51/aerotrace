# Engine 2 drive-loss contrast

Declared before collection on 6 November 2026. The pinned FlightGear 2024.1.7 A320-200-CFM uses engine 2 core speed to drive generator 2 and the Yellow engine-driven pump. The power transfer unit (PTU) can support Yellow pressure from Green. The Yellow electric pump is idle for these tests.

| Backup selection | Intervention | Expected candidate | Expected downstream effect |
| --- | --- | --- | --- |
| PTU automatic | Generator 2 and Yellow engine-driven pump failure flags | Independent generator and Yellow pump losses | Both source outputs lost, engine 2 fuel flow and core speed retained, Yellow pressure supported by transfer |
| PTU automatic | Native engine 2 fuel cutoff input | Engine 2 power loss | Fuel flow and core speed fall, generator and pump outputs lost, Yellow pressure supported by transfer |
| PTU off | Generator 2 and Yellow engine-driven pump failure flags | Independent generator and Yellow pump losses | Both source outputs lost, engine 2 fuel flow and core speed retained, sustained low Yellow line pressure |
| PTU off | Native engine 2 fuel cutoff input | Engine 2 power loss | Fuel flow and core speed fall, generator and pump outputs lost, sustained low Yellow line pressure |

Target about 6,000 ft (feet) and 230 kt (knots) with both engines running and valid baseline supplies. Record 28 simulator seconds of intervention and at least 10 simulator seconds after clearing the command. Plan about one poll per simulator second with independent channel timestamps. The paired loss precedes cutoff in each flight to preserve the ability to qualify with both engines. Allow new qualification before every intervention. Cutoff may leave engine power unrestored after command cleanup.

Test whether the same generator and pump loss can be separated using engine measurements. Withhold fuel flow and core speed from the same inputs in a separate measurement ablation. Both explanations should remain plausible. Inspect whether independently measured Yellow backup pressure accounts for retained or degraded line pressure. For stable end-of-intervention comparison, use the last six consecutive complete active polls. Use the preregistered thresholds in the study below for diagnosis.

Engineering thresholds for this narrow study are 50 pounds per hour for low fuel flow, 55% for low core speed, and 2,500 pounds per square inch (psi) for reduced Yellow engine-driven output. At least 2,500 psi indicates a useful alternate source for this contrast. Below 500 psi indicates insufficient source pressure. Yellow line pressure below 2,000 psi is low and at least 2,500 psi is retained. Between these ranges the pressure response is unresolved. Require six simulator seconds of continuous, closely sampled supply state after loss of the primary source to evaluate the Yellow pressure consequence. The thresholds define evidence and experimental response expectations for the pinned simulator.

These are four planned engineering contrasts at one target condition. The independent recipe uses two separate interventions. An engine cutoff produces a propulsion functional loss in the simulator. Operator inputs, expected candidate labels and active-phase boundaries remain outside diagnosis. The tests measure compatibility with this declared catalogue and configuration.

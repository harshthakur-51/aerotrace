# Five staged faults diagnosed live on the ESP32-P4

Declared on 17 November 2026 before injection. Run the pinned FlightGear A320-200-CFM near 6,000 feet and 230 knots with both engines running, the autopilot engaged and the power transfer unit (PTU) in automatic. Send every public observation to a Waveshare ESP32-P4-WIFI6-DEV-KIT running [the firmware](../../embedded/firmware), as in the [first live run](../board-live-20261116-01/RESULT.md).

After a fresh baseline admission, add one failure input per step from the [schedule](../../configs/board-live-five-mechanisms.json) and keep each selected to the end.

| Step | Added failure input | Target simulator seconds |
| ---: | --- | ---: |
| 1 | Generator 2 | 8 |
| 2 | Blue electric pump | 10 |
| 3 | Yellow engine-driven pump (EDP) | 10 |
| 4 | Blue hydraulic leak | 15 |
| 5 | Engine 2 fuel cutoff | 20 |

Clear all five and record a further 10 simulator seconds. Engine 2 may not relight after the cutoff is released.

Expect the board's explanation to grow at each step and to end with all five mechanisms as the only fit. The order gives each fault its own evidence. The generator and the Yellow pump fail while Engine 2 is still turning, so the later engine loss cannot explain them. Blue pressure falls before any fluid is lost, so the leak cannot explain it. The least certain step is the fourth: the leak must show as a falling Blue quantity within 35 simulator seconds. Expect every board reply to equal the Python fit of the same recording.

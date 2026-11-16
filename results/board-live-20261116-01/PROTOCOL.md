# Live flight diagnosed on the ESP32-P4

Declared on 16 November 2026 before injection. Run the pinned FlightGear A320-200-CFM near 6,000 feet and 230 knots with both engines running, the autopilot engaged and the power transfer unit (PTU) in automatic. Connect a Waveshare ESP32-P4-WIFI6-DEV-KIT running [the firmware](../../embedded/firmware) on its USB Serial/JTAG port. Send it every public observation as the experiment controller records it, at about one poll per second.

After a fresh baseline admission, enable the Generator 2 and Yellow engine-driven pump (EDP) failure inputs together for a target 28 simulator seconds. Clear both and record a further 10 simulator seconds.

Expect Generator 2 output and Yellow pump output to fall while Engine 2 keeps running, and expect the PTU to hold Yellow line pressure. Expect the board to move from no fault to the two-mechanism explanation, Generator 2 source path with Yellow EDP loss, and to not report Engine 2 power loss. Expect every board reply to equal the Python fit of the same recording.

The board receives the public observations only. Fault commands and native failure flags stay with the controller and are recorded separately.

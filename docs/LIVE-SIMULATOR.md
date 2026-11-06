# Connect the live A320 simulator

The connected cockpit launcher targets Windows and uses FlightGear 2024.1.7 with the A320-200-CFM model. The setup downloads about 2.2 GB, verifies the [pinned SHA-256 digests](../configs/flightgear-assets.json) and extracts the runtime and data under the checkout's `work/flightgear/` directory.

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -B scripts/setup-flight-sim.py
.\run-aircraft-sim.ps1
```

The launcher starts the cockpit and the [systems panel](http://127.0.0.1:8765). It reuses a compatible local cockpit if one is already running. Wait for the A320 startup sequence before operating the panel. The [FlightGear configuration](../configs/flightgear-a320.fgfsrc) selects a takeoff state on Honolulu runway 08L with the parking brake set. Both the simulator property server and the panel listen on loopback.

The panel displays measured source output, bus voltage, hydraulic pressure and quantity. Fault buttons act on the simulator's native failure flags. Use the recorded demo to inspect a completed airborne episode without interacting with those controls.

The separate [airborne experiment controller](../aircraft_debugger/airborne_experiment.py) checks stable flight and fresh readiness before setting a fault. It records observations and operator provenance in separate files and verifies cleanup for the flags it owns. The [recorded paired contrast](../results/pressure-pair-20261106-01/RESULT.md) documents an example with a qualified baseline.

import json
import time
from pathlib import Path
from aircraft_debugger.airborne_admission import READINESS_CHANNELS
from aircraft_debugger.flightgear import FlightGearClient, PropertySpec
client = FlightGearClient(timeout_s=1)
specs = {
    **READINESS_CHANNELS,
    "aircraft": PropertySpec("/sim/aircraft", "string"),
    "on_ground": PropertySpec("/gear/gear[1]/wow", "bool"),
    "airspeed": PropertySpec("/velocities/airspeed-kt"),
}
required = {
    "aircraft": "A320-200-CFM", "startup_in_progress": False,
    "startup_mismatch_reason": "XX", "engine_1_running": True,
    "engine_2_running": True, "on_ground": True, "generator_2_fault": False,
    "blue_leak_fault": False, "blue_pump_fault": False,
}
consecutive = 0
deadline = time.monotonic() + 100
with Path(__file__).with_name("startup-watch.jsonl").open("x", encoding="utf-8") as log:
    while time.monotonic() < deadline:
        snapshot = client.poll(specs)
        values = {name: reading.value for name, reading in snapshot.readings.items()}
        log.write(json.dumps(snapshot.to_dict()) + "\n")
        log.flush()
        ready = snapshot.complete and all(values[key] == val for key, val in required.items()) and values["airspeed"] < 20
        consecutive = consecutive + 1 if ready else 0
        if consecutive >= 3:
            print(json.dumps(values), flush=True)
            break
        time.sleep(1)
    else:
        raise RuntimeError("Ground startup did not qualify")

"""Owned simulator checkpoint and study PTU selection, separate from public data."""
import argparse
from dataclasses import asdict
import http.client
import json
from pathlib import Path

from aircraft_debugger.airborne_admission import PROPULSION_READINESS_CHANNELS
from aircraft_debugger.airborne_profile import PROPULSION_CHANNELS
from aircraft_debugger.flightgear import FlightGearClient, PropertySpec


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=("pause", "resume"))
parser.add_argument("ptu", choices=("auto", "off"))
parser.add_argument("output", type=Path)
args = parser.parse_args()
client = FlightGearClient(timeout_s=1)
selected = args.ptu == "auto"
channels = {
    **PROPULSION_CHANNELS, **PROPULSION_READINESS_CHANNELS,
    "clock_frozen": PropertySpec("/sim/freeze/clock", kind="bool"),
}


def snapshot():
    return client.poll(channels)


with args.output.open("x", encoding="utf-8", newline="\n") as output:
    def log(record):
        output.write(json.dumps(record, allow_nan=False) + "\n")
        output.flush()

    before = snapshot()
    log({"before": asdict(before)})
    values = {name: item.value for name, item in before.readings.items()}
    if (not before.complete or values["aircraft"] != "A320-200-CFM"
            or any(values[name] is not False for name in PROPULSION_READINESS_CHANNELS if name.endswith("_fault"))):
        raise RuntimeError("Expected pinned simulator with every studied input clear")
    if args.action == "resume":
        if not all(values[name] is True for name in ("paused", "clock_frozen", "engine_1_running", "engine_2_running")):
            raise RuntimeError("Resume requires a paused two-engine baseline")
        script = ('props.globals.getNode("/controls/hydraulic/switches/ptu").setBoolValue('
                  + str(int(selected)) + ');setprop("/sim/freeze/clock",0);setprop("/sim/freeze/master",0);')
    else:
        script = 'setprop("/sim/freeze/master",1);setprop("/sim/freeze/clock",1);'
    log({"request_script": script})
    connection = http.client.HTTPConnection(client.host, client.port, timeout=3)
    try:
        connection.request("POST", "/run.cgi?value=nasal",
                           json.dumps({"name": "", "children": [{"name": "script", "value": script}]}),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        log({"status": response.status, "response": response.read(4096).decode()})
        if response.status != 200:
            raise RuntimeError("Native control rejected")
    finally:
        connection.close()
    after = snapshot()
    log({"after": asdict(after)})
    desired_pause = args.action == "pause"
    if (not after.complete or after.readings["paused"].value is not desired_pause
            or after.readings["clock_frozen"].value is not desired_pause
            or after.readings["ptu_selected"].value is not selected):
        raise RuntimeError("Checkpoint readback did not match the requested state")
    print({name: after.readings[name].value for name in
           ("paused", "sim_time", "altitude", "airspeed", "ptu_selected", "engine_2_n2", "yellow_pressure")})

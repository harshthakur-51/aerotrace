"""Resume the owned, recovered A320 for another fresh admission window."""
import http.client
import json
from pathlib import Path

from aircraft_debugger.airborne_admission import READINESS_CHANNELS
from aircraft_debugger.flightgear import FlightGearClient, PropertySpec


client = FlightGearClient(timeout_s=1)
specs = {"aircraft": PropertySpec("/sim/aircraft", "string"),
         "paused": PropertySpec("/sim/freeze/master", "bool"),
         "clock_frozen": PropertySpec("/sim/freeze/clock", "bool"),
         **READINESS_CHANNELS}
before = client.poll(specs)
assert before.complete and before.readings["aircraft"].value == "A320-200-CFM"
assert before.readings["paused"].value is True and before.readings["clock_frozen"].value is True
assert all(before.readings[name].value is False
           for name in ("generator_2_fault", "blue_pump_fault", "blue_leak_fault"))
script = 'setprop("/sim/freeze/clock",0);setprop("/sim/freeze/master",0);'
connection = http.client.HTTPConnection("127.0.0.1", 8088, timeout=3)
try:
    body = json.dumps({"name": "", "children": [{"name": "script", "value": script}]})
    connection.request("POST", "/run.cgi?value=nasal", body, {"Content-Type": "application/json"})
    response = connection.getresponse()
    status, body = response.status, response.read().decode()
finally:
    connection.close()
after = client.poll(specs)
result = {"before": before.to_dict(), "script": script, "status": status, "response": body, "after": after.to_dict()}
with Path(__file__).with_name("resume-between-cases.json").open("x", encoding="utf-8") as output:
    json.dump(result, output, indent=2)
assert status == 200 and after.complete
assert after.readings["paused"].value is False and after.readings["clock_frozen"].value is False

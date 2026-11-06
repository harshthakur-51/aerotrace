"""Checkpoint pause after verified experiment cleanup; no fault writes."""
import http.client,json
from pathlib import Path
from aircraft_debugger.flightgear import FlightGearClient,PropertySpec
from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS
from aircraft_debugger.airborne_admission import READINESS_CHANNELS
c=FlightGearClient(timeout_s=1)
before=c.poll({'aircraft':PropertySpec('/sim/aircraft','string'),**READINESS_CHANNELS})
assert before.complete and before.readings['aircraft'].value=='A320-200-CFM'
assert before.readings['generator_2_fault'].value is False and before.readings['blue_leak_fault'].value is False and before.readings['blue_pump_fault'].value is False
script='setprop("/sim/freeze/master",1);setprop("/sim/freeze/clock",1);'
con=http.client.HTTPConnection('127.0.0.1',8088,timeout=3)
try:
 con.request('POST','/run.cgi?value=nasal',json.dumps({'name':'','children':[{'name':'script','value':script}]}),{'Content-Type':'application/json'})
 response=con.getresponse();status=response.status;body=response.read().decode()
finally:con.close()
after=c.poll({**AIRBORNE_CHANNELS,**READINESS_CHANNELS,'clock_frozen':PropertySpec('/sim/freeze/clock','bool'),'athr_active':PropertySpec('/systems/fadec/athr/active'),'gear_0':PropertySpec('/systems/gear/unit[0]/pos-actuator'),'gear_1':PropertySpec('/systems/gear/unit[1]/pos-actuator'),'gear_2':PropertySpec('/systems/gear/unit[2]/pos-actuator')})
record={'before':before.to_dict(),'requested_script':script,'http_status':status,'response':body,'after':after.to_dict()}
Path(__file__).with_name('checkpoint-pause.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8',newline='\n')
assert status==200 and after.complete and after.readings['paused'].value is True and after.readings['clock_frozen'].value is True
print(json.dumps({k:v.value for k,v in after.readings.items()}))

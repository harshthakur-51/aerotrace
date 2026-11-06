"""Read-only operator settling watch; fresh experiment admission is still required."""
import json,time
from pathlib import Path
from aircraft_debugger.flightgear import FlightGearClient
from aircraft_debugger.airborne_admission import AirborneAdmission,READINESS_CHANNELS
from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS,airborne_observation_record
from aircraft_debugger.airborne_record import load_settings
c=FlightGearClient(timeout_s=1);gate=AirborneAdmission(load_settings(Path('results/pressure-v2-protocol-20261106-01/qualification-B.json')))
log=Path(__file__).with_name('settling-watch.jsonl').open('x',encoding='utf-8',newline='\n');started=time.monotonic();i=0
while time.monotonic()-started<300:
 t=time.monotonic();r=airborne_observation_record(c.poll(AIRBORNE_CHANNELS),i,t);checks=c.poll(READINESS_CHANNELS);at=time.monotonic();g=gate.update(r,checks,at)
 log.write(json.dumps({'record':r,'readiness':checks.to_dict(),'evaluated_monotonic_s':at,'gate':g})+'\n');log.flush()
 if i%12==0 or g['qualified']:print(json.dumps({'poll':i,'state':{k:r['readings'][k]['value'] for k in ['altitude','airspeed','vertical_speed','autopilot_1','autothrust']},'gate':g}),flush=True)
 if g['qualified']:break
 i+=1;time.sleep(max(0,1-(time.monotonic()-t)))
else:raise RuntimeError('Settling bounded wait expired; no faults requested')
log.close()


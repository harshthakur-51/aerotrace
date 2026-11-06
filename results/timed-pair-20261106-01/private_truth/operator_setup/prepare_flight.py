"""One-session native setup trial; all thresholds are original simulator operator choices.
Not an aircraft takeoff procedure or validated flight controller. Writes only native
pilot inputs/FCU requests and freeze controls on abort; never computed state/gauges.
160 kt is an experimental rotation trigger, not a sourced aircraft V_R value.
"""
import http.client,json,time
from pathlib import Path
from aircraft_debugger.flightgear import FlightGearClient,PropertySpec
root=Path(__file__).parent
log=(root/'flight-setup.jsonl').open('x',encoding='utf-8',newline='\n')
def emit(x):
 x['local_monotonic_s']=time.monotonic();log.write(json.dumps(x)+'\n');log.flush()
def nasal(script):
 emit({'request_script':script})
 con=http.client.HTTPConnection('127.0.0.1',8088,timeout=4)
 try:
  con.request('POST','/run.cgi?value=nasal',json.dumps({'name':'','children':[{'name':'script','value':script}]}),{'Content-Type':'application/json'})
  r=con.getresponse();body=r.read(4096).decode();emit({'http_status':r.status,'response':body})
  if r.status!=200:raise RuntimeError('Native command rejected')
 finally:con.close()
c=FlightGearClient(timeout_s=1)
paths={k:PropertySpec(p,t) for k,p,t in [
 ('time','/sim/time/elapsed-sec','number'),('speed','/velocities/airspeed-kt','number'),
 ('agl','/position/altitude-agl-ft','number'),('alt','/position/altitude-ft','number'),
 ('wow','/gear/gear[1]/wow','bool'),('pitch','/orientation/pitch-deg','number'),
 ('bank','/orientation/roll-deg','number'),('ap1','/it-autoflight/output/ap1','bool'),
 ('air5','/systems/fmgc/airborne-5-secs','number'),('vs','/velocities/vertical-speed-fps','number')]}
def snap():
 s=c.poll(paths);emit({'snapshot':s.to_dict()})
 if not s.complete:raise RuntimeError('Setup observations incomplete')
 d={k:v.value for k,v in s.readings.items()};print(json.dumps(d),flush=True);return d
neutral='foreach(var p; ["/controls/flight/aileron","/controls/flight/elevator","/controls/flight/rudder","/controls/flight/aileron[1]","/controls/flight/elevator[1]","/controls/flight/rudder[1]"]) {setprop(p,0);}'
try:
 s=snap()
 if not s['wow'] or s['speed']>20:raise RuntimeError('Expected ready ground state')
 nasal(neutral+'setprop("/sim/freeze/master",0);setprop("/sim/freeze/clock",0);setprop("/controls/flight/speedbrake",0);setprop("/controls/gear/brake-parking",0);setprop("/controls/gear/brake-left",0);setprop("/controls/gear/brake-right",0);fmgc.Input.alt.setValue(6000);fmgc.Input.ktsMach.setBoolValue(0);fcu.FCUController.SPDPull();fmgc.Input.kts.setValue(200);setprop("/controls/engines/engine[0]/throttle",1);setprop("/controls/engines/engine[1]/throttle",1);fmgc.Input.toga.setBoolValue(1);')
 started=time.monotonic();rotated=False;gear=False;clean=False;engaged=False
 while time.monotonic()-started<150:
  s=snap()
  if s['wow'] and abs(s['bank'])>10:raise RuntimeError('Unexpected ground attitude')
  if not rotated and s['speed']>=160:
   nasal('setprop("/controls/flight/elevator",-0.18);');rotated=True
  if not s['wow'] and s['agl']>200 and not gear:
   nasal('controls.gearDown(-1);controls.gearDown(0);');gear=True
  if not s['wow'] and s['air5'] and s['agl']>250 and not engaged:
   nasal(neutral+'setprop("/controls/engines/engine[0]/throttle",0.625);setprop("/controls/engines/engine[1]/throttle",0.625);fmgc.Input.fd1.setBoolValue(1);fmgc.Input.hdg.setValue(math.round(getprop("/it-autoflight/internal/heading")));fmgc.Input.lat.setValue(0);fcu.FCUController.ALTPull();if (!fmgc.Output.ap1.getBoolValue()) {fcu.FCUController.AP1();}')
   engaged=True
  if engaged and not s['ap1'] and s['agl']>500:
   nasal('if (!fmgc.Output.ap1.getBoolValue()) {fcu.FCUController.AP1();}')
  if s['ap1'] and s['agl']>1500 and s['speed']>=195 and not clean:
   nasal('setprop("/controls/flight/flaps",0);setprop("/controls/flight/speedbrake-arm",0);fmgc.Input.kts.setValue(230);');clean=True
  if s['ap1'] and clean and s['agl']>2000:
   emit({'setup_status':'native_climb_established','note':'Not qualification; target 6000ft/230kt still to be reached.'});print('NATIVE_CLIMB_ESTABLISHED',flush=True);break
  time.sleep(.6)
 else:raise RuntimeError('Native takeoff/setup time bound exceeded')
except BaseException as e:
 emit({'abort':type(e).__name__,'message':str(e)})
 try:nasal('setprop("/controls/flight/elevator",0);setprop("/controls/flight/aileron",0);setprop("/sim/freeze/master",1);setprop("/sim/freeze/clock",1);')
 except Exception:pass
 raise
finally:log.close()


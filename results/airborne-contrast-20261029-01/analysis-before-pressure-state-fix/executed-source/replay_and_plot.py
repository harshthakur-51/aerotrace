"""Blind prefix replay and figure from one explicit public observation file.
No experiment labels, phase boundaries, manifests, sibling files or native IO.
"""
import hashlib,json,subprocess,sys
from pathlib import Path
from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.airborne_evidence import analyze_airborne_observations
source=Path(sys.argv[1]);output=Path(sys.argv[2]);rows=list(iter_profile_observations(source))
timeline=[]
for end in range(1,len(rows)+1):
 report=analyze_airborne_observations(rows[:end]);row=rows[end-1]
 timeline.append({'sample_index':row['sample_index'],'sim_time_s':row['readings']['sim_time']['value'],
   'assessment':report['assessment'],'current_state':report['current_state'],
   'explanations':report['explanations'],'impact':report['impact'],
   'current_context_quality':report['airborne_context']['quality'],
   'evidence_ids':[x['evidence_id'] for x in report['ledger']]})
with (output/'timeline.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(timeline,f,indent=2);f.write('\n')
project=Path.cwd();hashes={};archives={}
for name in ['aircraft_debugger/__init__.py','aircraft_debugger/airborne_evidence.py','aircraft_debugger/airborne_profile.py','aircraft_debugger/evidence.py','aircraft_debugger/observations.py']:
 data=(project/name).read_bytes();rel=Path('executed-source')/name;dest=output/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);hashes[name]=hashlib.sha256(data).hexdigest();archives[name]=rel.as_posix()
selfdata=Path(__file__).read_bytes();(output/'executed-source/replay_and_plot.py').write_bytes(selfdata);hashes['replay_and_plot.py']=hashlib.sha256(selfdata).hexdigest();archives['replay_and_plot.py']='executed-source/replay_and_plot.py'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
x=[r['readings']['sim_time']['value'] for r in rows]
def vals(k):return [r['readings'].get(k,{}).get('value') if r['readings'].get(k,{}).get('valid') else float('nan') for r in rows]
fig,axes=plt.subplots(3,1,figsize=(11,8.5),sharex=True,constrained_layout=True)
fig.suptitle('Native airborne hydraulic depletion: inventory, pressure and flight context',fontsize=14)
a=axes[0];a.plot(x,vals('generator_2_voltage'),color='#b2182b',marker='.',label='Generator 2 output');a.plot(x,vals('ac_bus_2'),color='#2166ac',label='AC bus 2 supply');a.set_ylabel('Voltage (V)');a.set_ylim(-5,130);a.legend(loc='lower left');a.grid(alpha=.2)
a=axes[1];a.plot(x,vals('blue_quantity'),color='#333333',label='Blue quantity');a.set_ylabel('Quantity (raw model units)');a.set_ylim(0,8.5);a.grid(alpha=.2);b=a.twinx();b.plot(x,vals('blue_pressure'),color='#cc7700',linestyle='--',label='Blue pressure');b.set_ylabel('Pressure (psi)');b.set_ylim(0,3500);a.legend(loc='lower left');b.legend(loc='lower right')
a=axes[2];a.plot(x,vals('altitude'),color='#762a83',label='Position altitude');a.set_ylabel('Altitude (ft)');a.set_ylim(9500,10500);a.grid(alpha=.2);b=a.twinx();b.plot(x,vals('airspeed'),color='#007d77',linestyle='--',label='Calibrated airspeed');b.set_ylabel('Airspeed (kt)');b.set_ylim(225,275);a.legend(loc='lower left');b.legend(loc='lower right');a.set_xlabel('Simulator elapsed time (s)')
fig.savefig(output/'native-response.png',dpi=150);plt.close(fig)
meta={'purpose':'Blind public-input prefix replay and native-response plot; no private truth read',
 'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project).decode().strip(),
 'observations_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'samples':len(rows),
 'source_sha256':hashes,'executed_source_archives':archives,
 'artifact_sha256':{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ['report.json','report.md','timeline.json','native-response.png']},
 'axis_units':{'V':'volts','psi':'pounds per square inch','ft':'feet','kt':'knots (one nautical mile per hour)','s':'simulator seconds','raw model units':'physical quantity unit unresolved'},
 'plot_limits':'Axis display ranges are visualization choices, not operating limits; All recorded samples are plotted with no phase or stability filtering.',
 'timeline_semantics':'Each prefix ends at a public sample index; no operator phase or injection label selects the diagnostic state.'}
with (output/'provenance.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(meta,f,indent=2);f.write('\n')
print(json.dumps({'samples':len(rows),'categories':list(dict.fromkeys(t['assessment']['category'] for t in timeline)),'events':[(x['kind'],x['confirmation']['sample_index']) for x in report['ledger']]}))

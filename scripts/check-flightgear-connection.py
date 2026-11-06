"""Live connection check against the local A320 model, not diagnostic evaluation.

Requires a fresh, on-ground A320-200-CFM with its native takeoff state ready.
Mutates native generator/leak flags and clears only flags enabled by this check.
The aircraft model may restore quantity when a leak is cleared. Keep interactive
panel polling stopped during this controlled check. All writes are operator truth;
only selected observations are saved to observations.jsonl.
"""
from pathlib import Path
import argparse
import json
import time
from aircraft_debugger.flightgear import FlightGearClient
from aircraft_debugger.sim_panel import CHANNELS, FAULT_PATHS, PanelState


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    private=args.output/'private_truth'
    private.mkdir()
    client=FlightGearClient(timeout_s=1.0,max_workers=4)
    operator=PanelState(client)
    checks=[]
    actions=[]
    owned=set()
    samples=[]
    def observe(stage):
        snapshot=client.poll(CHANNELS).to_dict()
        if not snapshot['complete']:
            raise RuntimeError('Incomplete live observations; no healthy values fabricated')
        samples.append(snapshot)
        with (args.output/'observations.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(snapshot,allow_nan=False)+'\n')
        checks.append({'stage':stage,'sample_index':len(samples)-1})
        return {k:r['value'] for k,r in snapshot['readings'].items()}
    def command(fault,enabled):
        status,result=operator.command({'fault':fault,'enabled':enabled})
        actions.append({'fault':fault,'enabled':enabled,'status':status,'result':result})
        if status!=200:
            raise RuntimeError(str(result))
        if enabled: owned.add(fault)
        else: owned.discard(fault)
    try:
        baseline=observe('healthy_ready')
        if baseline['aircraft']!='A320-200-CFM' or baseline['generator_2_voltage']<100 or baseline['airspeed']>20:
            raise RuntimeError('Use the fresh, ready, on-ground A320 before this experiment')
        for fault,path in FAULT_PATHS.items():
            value=client.read_property(path,'bool')
            if not value.valid or value.value is not False:
                raise RuntimeError('Native flags must be valid and clear before the experiment')
        command('generator_2',True)
        time.sleep(2)
        failed=observe('generator_2_failed')
        if not failed['generator_2_voltage']<1:
            raise AssertionError('Generator output did not respond to its native failure')
        if not failed['ac_bus_2']>100:
            raise AssertionError('Expected alternate bus supply was not observed')
        command('generator_2',False)
        time.sleep(2)
        restored=observe('generator_flag_cleared')
        command('blue_leak',True)
        time.sleep(4)
        leaking=observe('blue_leak_active')
        if not leaking['blue_quantity']<restored['blue_quantity']:
            raise AssertionError('Hydraulic quantity did not respond to its native leak')
        command('blue_leak',False)
        time.sleep(2)
        cleared=observe('blue_leak_flag_cleared')
        print('Generator voltage:',baseline['generator_2_voltage'],'->',failed['generator_2_voltage'],'V',flush=True)
        print('Bus 2 voltage while generator failed:',failed['ac_bus_2'],'V',flush=True)
        print('Blue quantity (raw model scale):',restored['blue_quantity'],'->',leaking['blue_quantity'],'->',cleared['blue_quantity'],flush=True)
        print('Blue pressure during brief leak:',leaking['blue_pressure'],'psi',flush=True)
    finally:
        for fault in list(owned):
            try: command(fault,False)
            except Exception as exc: actions.append({'cleanup_error':str(exc),'fault':fault})
        (private/'checks.json').write_text(json.dumps({'kind':'descriptive live simulator coupling check; no diagnostic engine','checks':checks,'operator_actions':actions},indent=2),encoding='utf-8')
    print('Live native-failure connection check passed. Results:',args.output,flush=True)


if __name__=='__main__':
    main()

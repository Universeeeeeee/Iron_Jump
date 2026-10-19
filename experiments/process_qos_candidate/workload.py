"""One process-only QoS variable; reuse original native and complete work sources."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from qos import API,configure

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

if __name__=='__main__':
    name=sys.argv[1];plan=read(HERE/'plan01.json');assert name in plan['cases']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    record=dict(case=name,errors=[]);code=1
    try:
        api=API();record['configuration']=configure(api,plan['qos_variants'][name])
        native=load('original_native_probe',ROOT/'experiments/cpu_execution_probe/probe.py')
        native.HERE=HERE/'runs'/(name+'_native');native.HERE.mkdir(exist_ok=False)
        (native.HERE/'plan01.json').write_bytes((ROOT/'experiments/cpu_execution_probe/plan01.json').read_bytes())
        assert native.run()==0
        runner=load('original_fixed_preparation_work',ROOT/'experiments/cpu_state_observation/workload.py');runner.HERE=HERE
        code=runner.child(name)
        record['at_end']=api.read();assert record['at_end']==record['configuration']['after']
    except BaseException as exc:record['errors'].append(repr(exc));code=1
    finally:
        record['returncode']=code
        with (HERE/'runs'/(name+'_qos.json')).open('x') as f:json.dump(record,f,indent=2)
    raise SystemExit(code)

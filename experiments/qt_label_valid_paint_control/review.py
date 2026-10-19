"""Re-read archived delivered pixels; keep correctness separate from effect."""
import hashlib
import json
import math
from pathlib import Path
import zipfile
from check import check

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');data=read(HERE/'result01.json');target=read(HERE/'control02.status.json')
    assert data['plan_sha256']==sha(HERE/'plan01.json') and all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert plan['process_budget']==1 and plan['retry_budget']==0 and not plan['performance_AB'] and not plan['performance_endpoints']
    qualification=check(data,plan)
    assert data['passed'] and target['confirmed_exit'] and target['observation_complete'] and target['native_query_success']
    assert target['native_exit_code']==target['managed_exit_code']==0
    assert (HERE/'control02.stderr.log').read_bytes()==b''
    post=read(HERE/'post01.json')
    assert post['sources_and_modules_unchanged'] and not post['current_pid_records']
    assert set(post['locks'])=={'active.lock','launch02.lock'}
    transport=read(HERE/'transport01.json');archive=HERE/'runs/evidence01.zip';assert sha(archive)==transport['sha256']
    checked=[]
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('manifest01.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in manifest['files'].items())
        assert len(manifest['files'])==transport['manifest_files']
        assert all(n+'/' in z.namelist() for n in manifest['locks'])
        assert all(manifest['files'][n]==v for n,v in plan['sources'].items())
        assert manifest['files']['result01.json']==sha(HERE/'result01.json')
        for row,case in zip(data['cases'],plan['cases']):
            delivered={}
            for mode,meta in row['modes'].items():
                raw=z.read(f"runs/{row['id']}_{mode}.argb");delivered[mode]=raw
                assert hashlib.sha256(raw).hexdigest()==meta['pixels_sha256']
                assert len(raw)==meta['byte_count']==meta['bytes_per_line']*meta['height']
                assert meta['width']==math.ceil(case['size'][0]*case['target_dpr'])
                assert meta['height']==math.ceil(case['size'][1]*case['target_dpr'])
                assert meta['bytes_per_line']==meta['width']*4
                assert raw!=bytes.fromhex('030201ff')*(len(raw)//4)
            assert delivered['golden']==delivered['binding']==delivered['bridge']
            checked.append(dict(id=row['id'],full_archived_bytes_equal=True,bytes_per_mode=len(delivered['golden'])))
    result=dict(correctness_control_pass=qualification['correctness_control_pass'],archived_pixel_cases=checked,
        invalid_input_pairs=len(data['invalid_inputs']),faults_caught_at_same_base_boundary=all(v['caught_at_base_call']==1 and v['same_exception_instance'] for v in data['injected_callbacks']),
        native_exit_code_confirmed=0,expected_locks_retained=True,formal_source_or_existing_painter_modified=False,
        limitations=['Only the specified synthetic QLabel/QProxyStyle domain is covered; not the real AnnotationCanvas, pose overlay or complete GUI/report lifecycle.',
            'Six complete image triplets are retained and independently compared. Fault recovery byte comparisons were made at runtime; those additional images were not retained.',
            'Private Shiboken ABI is pinned to these exact files; no support for a different wheel/build or arbitrary multiple inheritance is claimed.',
            'No actual workload perturbation, model/input equivalence, root contribution, latency benefit or field repair is certified.',
            'All previous failures, including the earlier null-exit-code control, stay unchanged.'],
        performance_experiment_started=False,actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,
        bindings={p.name:sha(p) for p in (Path(__file__),HERE/'plan01.json',HERE/'result01.json',HERE/'post01.json',
            HERE/'control02.status.json',HERE/'transport01.json',HERE/'launch_binding01.json')})
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))

"""Authorized candidate, full original saved-input oracle, no timing comparison."""
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'semantic_plan01.json').read_text());folder=HERE/'runs/semantic01';folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir();record=dict(errors=[],helper_calls=0,actual_load_disturbance_pass=False)
    original=None
    try:
        root=Path(plan['replay_root']);sys.path.insert(0,str(root/'experiments/walk_compute_offline_diagnosis'));import replay
        import candidate
        from engine.device_quality_session import DeviceQualitySession
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
        assert sha(Path(replay.__file__))==plan['replay_sha256'] and sha(root/'engine/device_quality_session.py')==plan['original_module_sha256']
        baseline=replay.read(root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];assert all(sha(root/n)==v for n,v in baseline.items())
        assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
        helper=candidate.runtime_mask_equal
        def counted(a,b):record['helper_calls']+=1;return helper(a,b)
        candidate.runtime_mask_equal=counted
        original=candidate.install(plan['original_function_source_sha256'])
        app=replay.QCoreApplication.instance() or replay.QCoreApplication([]);trial=replay.Trial(Path(plan['input_root']));trial.oracle()
        assert record['helper_calls']>0
        assert all(sha(root/n)==v for n,v in baseline.items()) and all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
        record.update(complete=True,original_report_and_state_exact=True,report_sha256=trial.report_hash,formal_start=trial.start,formal_end=trial.end,source_files_unchanged=len(baseline))
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        if original is not None:DeviceQualitySession.on_frame=original
        record['method_restored']=original is None or DeviceQualitySession.on_frame is original
        with (folder/'result.json').open('x') as f:json.dump(record,f,indent=2)
    print(json.dumps(record));raise SystemExit(bool(record['errors']))

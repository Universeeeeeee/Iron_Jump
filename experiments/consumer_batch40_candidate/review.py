import json,sys
from pathlib import Path
root=Path(r'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01');tool=root/'experiments/consumer_batch40_candidate';sys.path.insert(0,str(tool))
from metrics import measure
plan=json.loads((tool/'plan02.json').read_text());value=measure(tool/'runs/cohort01/batch40/capture',Path(plan['input_root'])/'raw_frames.npz')
value['severe']=value['observed_queue_lower']>=1000 and value['scheduled_max_ms']>=1000;value['bounded_250']=value['queue_upper']<=250 and value['scheduled_max_ms']<=250
result={'case':value,'conclusion':'Consumer isolation remains severe and is not sufficient.' if value['severe'] else 'Consumer isolation is bounded but same-boot order confounds causality.' if value['bounded_250'] else 'Consumer isolation is neither severe nor within the 250 absolute gate.','formal_fix_verified':False,'field_fix_verified':False}
(tool/'result01.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

"""New font-ready fixture; preserve the original failed plan/window."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    old=json.loads((HERE/'plan01.json').read_text())
    assert all(sha(HERE/n)==v for n,v in old['sources'].items())
    p=dict(old);p['prior_failed_plan_sha256']=sha(HERE/'plan01.json')
    p['fixture_revision']='font_ready02';p['process_font_directory']=(HERE/'font_fixture04').as_posix()
    p['existing_font_files']={n:sha(Path(n)) for n in ('C:/Windows/Fonts/segoeui.ttf','C:/Windows/Fonts/msyh.ttc')}
    proof=json.loads((HERE/'font_preflight04.json').read_text());assert proof['font_delivery_pass'] and not proof['Qt_messages']
    p['font_preflight_sha256']=sha(HERE/'font_preflight04.json')
    p['sources']={n:sha(HERE/n) for n in ('derive.py','bridge.py','binding_review01.json','control03.py','check.py','test_derive.py',
        'freeze03.py','reference_plan01.json','process_helper.ps1','launch03.ps1','font_probe04.py','font_fixture04.json')}
    p['font_delivery_required']=True;p['font_probe_raster_count']=2;p['retries']=0
    with (HERE/'plan02.json').open('x') as f:json.dump(p,f,indent=2)
    print(json.dumps(p,indent=2))

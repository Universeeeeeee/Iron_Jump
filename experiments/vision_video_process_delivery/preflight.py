"""Windows source/input/model and runtime gate; never starts model or decodes media."""
import hashlib
import importlib.metadata
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((HERE/'plan03.json').read_text());assert not (HERE/'runs').exists()
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert sha(HERE/'selection01.json')==p['selection_sha256']
    root=Path(p['input_root']);assert all(sha(root/n)==v for n,v in p['media_sha256'].items())
    assert sha(Path(p['model_path']))==p['model_sha256']
    for name in p['sources']:compile((HERE/name).read_text(encoding='utf-8'),name,'exec')
    runtime=dict(python=__import__('sys').version,mediapipe=importlib.metadata.version('mediapipe'),numpy=importlib.metadata.version('numpy'),opencv=importlib.metadata.version('opencv-python'))
    with (HERE/'preflight03.json').open('x') as f:json.dump(dict(passed=True,plan_sha256=sha(HERE/'plan03.json'),runtime=runtime,model_or_media_started=False),f,indent=2)
    print(json.dumps(runtime))

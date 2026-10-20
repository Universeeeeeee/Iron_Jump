import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
 p=json.loads((HERE/'plan03.json').read_text());assert all(sha(HERE/n)==v for n,v in p['sources'].items())
 source=Path(p['retained_window_path']);manifest=json.loads((HERE/p['retained_manifest_file']).read_text());assert all(sha(source/n)==v for n,v in manifest['files'].items())
 proof=dict(passed=True,plan_sha256=sha(HERE/'plan03.json'),target_started=False,target_retried=False);(HERE/'preflight_two03.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))

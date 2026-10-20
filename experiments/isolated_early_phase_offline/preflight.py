import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
 p=json.loads((HERE/'plan01.json').read_text());assert not (HERE/'result01.json').exists();assert all(sha(HERE/n)==v for n,v in p['sources'].items());assert all(sha(ROOT/n)==v for n,v in p['formal_sha256'].items());folder=Path(p['input_folder']);assert all(sha(folder/n)==v for n,v in p['input_sha256'].items());compile((HERE/'profile.py').read_text(encoding='utf-8'),'profile.py','exec');proof=dict(passed=True,plan_sha256=sha(HERE/'plan01.json'),workload_started=False);(HERE/'preflight01.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))

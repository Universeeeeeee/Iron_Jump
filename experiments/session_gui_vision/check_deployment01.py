import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
p=json.loads((HERE/'plan01.json').read_text());missing=[];mismatch=[]
for n,v in p['existing_sources'].items():
 f=ROOT/n
 if not f.exists():missing.append(n)
 elif hashlib.sha256(f.read_bytes()).hexdigest()!=v:mismatch.append(n)
result=dict(missing=missing,mismatch=mismatch,workload_started=False)
with (HERE/'deployment_check01.json').open('x') as out:json.dump(result,out,indent=2)
print(json.dumps(result))

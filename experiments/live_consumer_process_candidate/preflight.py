import hashlib,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
 p=json.loads((HERE/'plan01.json').read_text());assert all(sha(HERE/n)==v for n,v in p['sources'].items());assert all(sha(ROOT/n)==v for n,v in p['formal_sha256'].items());
 for n in p['sources']:
  if n.endswith('.py'):compile((HERE/n).read_text(encoding='utf-8'),n,'exec')
 r=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],capture_output=True,text=True);result=dict(returncode=r.returncode,output=r.stdout+r.stderr,live_USB_started=False);(HERE/'tests01.json').write_text(json.dumps(result,indent=2));assert r.returncode==0;print(json.dumps(result))

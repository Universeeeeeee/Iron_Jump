import subprocess,json,ctypes
from qos import API,Throttle,configure
assert ctypes.sizeof(Throttle)==12
r=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s','.','-p','test_*.py'],capture_output=True)
assert r.returncode==0,r.stderr
a=API();default=configure(a,'default');optout=configure(a,'optout')
print(json.dumps(dict(returncode=r.returncode,stdout=r.stdout.decode(),stderr=r.stderr.decode(),default=default,optout=optout,scope='Ephemeral preflight process only; no workload')))

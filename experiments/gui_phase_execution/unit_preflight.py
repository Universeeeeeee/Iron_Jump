import subprocess,json
r=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s','.','-p','test_*.py'],capture_output=True)
print(json.dumps(dict(returncode=r.returncode,stderr=r.stderr.decode(),no_workload=True)))
raise SystemExit(r.returncode)

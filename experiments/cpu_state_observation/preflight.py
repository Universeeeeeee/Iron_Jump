import subprocess,json,ctypes,monitor
assert ctypes.sizeof(monitor.Value)==16 and ctypes.sizeof(monitor.Power)==12
r=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s','.','-p','test_*.py'],capture_output=True)
print(json.dumps(dict(returncode=r.returncode,stdout=r.stdout.decode(),stderr=r.stderr.decode(),native_layout_pass=True)))
raise SystemExit(r.returncode)

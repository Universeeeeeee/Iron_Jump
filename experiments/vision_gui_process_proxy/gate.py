import hashlib
import json

def require(folder):
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=read(folder/'plan02.json');proof=read(folder/'preflight_passed02.json')
    assert proof['passed'] and proof['plan_sha256']==sha(folder/'plan02.json') and proof['tests_sha256']==sha(folder/'windows_tests02.json')
    assert all(sha(folder/name)==digest for name,digest in plan['sources'].items())
    return plan

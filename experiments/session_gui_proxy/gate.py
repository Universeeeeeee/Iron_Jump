import hashlib
import json

def require_gate(folder):
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=read(folder/'plan01.json');proof=read(folder/'preflight_passed01.json')
    assert proof['passed'] and proof['plan_sha256']==sha(folder/'plan01.json') and proof['tests_sha256']==sha(folder/'windows_tests01.json')
    assert all(sha(folder/n)==v for n,v in plan['sources'].items())
    return plan

import hashlib
import json

def require_gate(folder):
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=json.loads((folder/'plan01.json').read_text());proof=json.loads((folder/'preflight_passed01.json').read_text())
    assert proof['passed'] and proof['plan_sha256']==sha(folder/'plan01.json') and proof['tests_sha256']==sha(folder/'windows_tests01.json')
    assert all(sha(folder/name)==digest for name,digest in plan['sources'].items())
    return plan

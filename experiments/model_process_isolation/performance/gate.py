import hashlib
import json

def require_gate(folder):
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    gate=read(folder/'preflight_passed01.json')
    if not gate['passed'] or gate['plan_sha256']!=sha(folder/'plan01.json') or gate['test_record_sha256']!=sha(folder/'windows_tests01.json'):raise ValueError('Failed or stale preflight')
    return gate

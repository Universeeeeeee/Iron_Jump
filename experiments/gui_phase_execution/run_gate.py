"""Full source/test gate required by controller and every target invocation."""
import hashlib
import json

def require_gate(folder):
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=read(folder/'plan02.json');gate=read(folder/'preflight02.json')
    if not plan.get('launch_authorized_by_this_plan') or not gate.get('passed'):raise ValueError('GUI preflight incomplete')
    if gate['plan_sha256']!=sha(folder/'plan02.json') or gate['tests_sha256']!=sha(folder/'windows_tests02.json'):raise ValueError('Stale GUI preflight')
    if not all(sha(folder/n)==v for n,v in plan['sources'].items()):raise ValueError('Changed GUI source')
    return plan

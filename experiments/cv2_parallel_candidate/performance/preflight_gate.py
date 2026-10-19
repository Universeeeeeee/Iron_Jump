"""A new plan needs its own passed, source-bound test gate before any case starts."""
import hashlib
import json

def require_gate(folder):
    proof=json.loads((folder/'preflight_passed01.json').read_text())
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if not proof.get('passed') or not proof.get('windows_tests_passed') or not proof.get('observed_delivery_and_semantics_pass'):
        raise ValueError('Performance preflight not passed')
    if proof['plan_sha256']!=digest(folder/'plan01.json') or proof['test_record_sha256']!=digest(folder/'windows_tests01.json') or proof['delivery_review_sha256']!=digest(folder/'delivery_review01.json'):
        raise ValueError('Stale or altered performance preflight evidence')
    return proof

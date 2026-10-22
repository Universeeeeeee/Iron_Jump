"""Check actual runtime identity before accepting same-event stage observations."""
import json
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
folder = Path(sys.argv[1])
subprocess.run([sys.executable, str(here.parent / 'wire_boundary_replay_20261022/analyze_wire.py'), str(folder)], check=True)
result = json.loads((folder / 'analysis.json').read_text())
for case in result['cases']:
    context = [json.loads(p.read_text()) for p in (folder / case['case']).glob('binding_*.json')]
    expected = case['case'].split('_')[1]
    assert len(context) == (2 if case['mode'] == 'process40' else 1)
    run = json.loads((folder / case['case'] / 'result.json').read_text())
    assert run['parent_pid'] in {item['pid'] for item in context}
    for item in context:
        assert item['actual'].lower() == item['expected'] == expected
        assert item['session_id'] == 0 and item['priority_class'] == 32
        assert item['loaded_bindings'] == [item['actual']]
    case['binding_context'] = context
result['limits'].append('Qt binding and Qt major version change together. This small fixed matrix neither isolates a binding implementation mechanism nor calibrates live desktop/camera/SDK performance. Session 0 / offscreen is not Session 1 / windows.')
(folder / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')

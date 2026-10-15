"""Run independent sampler modes sequentially, retaining every failure."""
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


if __name__ == '__main__':
    statuses = []
    for kind in ('gil', 'all', 'native'):
        for mode in ('run', 'walk'):
            name = f'external_{mode}_{kind}_01'
            command = [sys.executable, str(HERE / 'external.py'), '--mode', mode, '--kind', kind]
            print('START', name, flush=True)
            with (HERE / (name + '_driver.log')).open('xb') as stream:
                completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=150)
            statuses.append({'mode': mode, 'kind': kind, 'returncode': completed.returncode})
            (HERE / 'external_status.json').write_text(json.dumps(statuses, indent=2) + '\n')
            print('DONE', name, completed.returncode, flush=True)
    # A native sampling failure is evidence about the measurement's limits, not a reason to discard other runs.

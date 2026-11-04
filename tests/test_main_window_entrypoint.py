"""Launching ui/main_window.py must delegate before importing project modules."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('cwd', [ROOT, ROOT / 'ui'])
def test_direct_script_restarts_same_python_as_package_from_root(tmp_path, cwd):
    # Intercept only the delegated module runner in a fresh interpreter. This
    # exercises the real exec, without starting hardware or a GUI in the test.
    (tmp_path / 'sitecustomize.py').write_text('''
import json, os, runpy, sys
def probe(name, alter_argv=True):
    print(json.dumps({'module': name, 'cwd': os.getcwd(), 'python': sys.executable,
                      'arguments': sys.argv[1:]}))
runpy._run_module_as_main = probe
''')
    result = subprocess.run([sys.executable, str(ROOT / 'ui/main_window.py'), 'entry-probe'],
                            cwd=cwd, env={**os.environ, 'PYTHONPATH': str(tmp_path)},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['module'] == 'ui.main_window'
    assert Path(value['cwd']) == ROOT
    assert Path(value['python']) == Path(sys.executable)
    assert value['arguments'] == ['entry-probe']

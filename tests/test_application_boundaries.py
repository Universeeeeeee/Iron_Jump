"""Guard package imports, worker startup, and snapshot-only report rendering."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_application_packages_do_not_modify_import_search_path():
    failures = []
    for package in ("agent", "camera", "config", "engine", "hardware", "reporting", "tools", "ui", "vision"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and ast.unparse(node) == "sys.path":
                    failures.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert failures == []


def test_result_contracts_and_builders_do_not_import_runtime_layers():
    forbidden = {"ui", "engine", "hardware", "camera", "qtpy", "PySide6", "PyQt5"}
    failures = []
    for package in ("config", "reporting"):
        for path in (ROOT / package).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                if any(name.split(".")[0] in forbidden for name in names):
                    failures.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert failures == []


def test_report_view_renders_all_saved_modes_without_engine(tmp_path):
    from tests.report_export_fixtures import export_reports
    from data.subject_store import _report_detail
    fixture = tmp_path / "reports.json"
    fixture.write_text(json.dumps({name: _report_detail(report)
                                  for name, report in export_reports().items()}))
    # A fresh interpreter rejects engine imports at every transitive level.
    code = '''
import importlib.abc, json, sys
class NoEngine(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "engine" or fullname.startswith("engine."):
            raise AssertionError("Report rendering imported " + fullname)
sys.meta_path.insert(0, NoEngine())
from qtpy.QtWidgets import QApplication
from data.subject_store import _report_from_detail
from ui.views.report_view import ReportView
from reporting.excel import build_report_workbook
app = QApplication([])
view = ReportView()
with open(sys.argv[1] + "/reports.json") as source:
    reports = json.load(source)
for name, saved in reports.items():
    restored = _report_from_detail(saved)
    view.load_report(restored)
    build_report_workbook(restored).save(sys.argv[1] + "/" + name + ".xlsx")
    print(name)
view.close()
'''
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_API": "pyside6"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert len(list(tmp_path.glob("*.xlsx"))) == 6


def test_agent_client_starts_module_from_project_root(qtbot, tmp_path):
    from ui.llm_client import AgentWorkerClient
    from unittest.mock import patch
    client = AgentWorkerClient(sys.executable, str(ROOT / "agent/worker.py"),
                               port_file=tmp_path / "port.json")
    with patch("qtpy.QtCore.QProcess") as process:
        process.return_value.waitForStarted.return_value = True
        assert client.start()
        process.return_value.setArguments.assert_called_once_with(["-m", "agent.worker"])
        process.return_value.setWorkingDirectory.assert_called_once_with(str(ROOT))


def test_worker_package_resolves_system_config_without_agent_directory_on_path():
    code = '''
import runpy, sys
from pathlib import Path
runpy.run_module("agent.worker", run_name="entrypoint_probe")
import config.test_config, agent.config
assert Path(config.test_config.__file__).parent == Path.cwd() / "config"
assert Path(agent.config.__file__).parent == Path.cwd() / "agent/config"
assert str(Path.cwd() / "agent") not in sys.path
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", ["tools.vision_live", "tools.vision_event_validator",
                                    "tools.annotate_foot_contacts", "tools.replay_foot_classifier",
                                    "tools.mac_mediapipe_validator", "tools.benchmark_report_agent",
                                    "engine.single_foot_tracker", "engine.spatial_clusterer",
                                    "hardware.receive"])
def test_module_command_help_runs_without_path_injection(module):
    result = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout

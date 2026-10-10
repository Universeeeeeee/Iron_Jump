"""Compare new snapshot export to workbooks saved by the original UI method."""
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook
import pytest

from reporting.excel import build_report_workbook, has_export_data
from tests.report_export_fixtures import export_reports, workbook_cells


@pytest.fixture(scope="module")
def reports():
    return export_reports()


@pytest.mark.parametrize("name", ["jump", "treadmill_gait", "treadmill_running", "walking", "overground_running", "legacy_jump"])
def test_workbook_matches_pre_extraction_file(name, reports):
    baseline = json.loads((Path(__file__).parent / "fixtures/report_export_v1.json").read_text())
    report = reports[name]
    assert has_export_data(report)
    book = build_report_workbook(report)
    stream = BytesIO()
    book.save(stream)
    book.close()
    stream.seek(0)
    actual = load_workbook(stream)
    assert workbook_cells(actual) == baseline["cases"][name]
    actual.close()


def test_export_module_does_not_import_ui_or_qt():
    subprocess.run([sys.executable, "-c", "import sys; import reporting.excel; "
                    "assert not any(k == 'qtpy' or k.startswith(('PySide6', 'ui.')) for k in sys.modules)"], check=True)

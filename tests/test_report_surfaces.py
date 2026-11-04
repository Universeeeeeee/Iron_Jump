"""Check painted report surfaces even when the system palette is light."""

import pytest
from qtpy.QtGui import QColor, QPalette
from qtpy.QtWidgets import QApplication, QTextBrowser

from ui.theme import PALETTE
from ui.views.report_view import ReportView


@pytest.fixture
def report_view(qtbot, qapp):
    old_palette = qapp.palette()
    old_style = qapp.style().objectName()
    old_qss = qapp.styleSheet()
    qapp.setStyle("Fusion")
    qapp.setStyleSheet("")
    palette = qapp.palette()
    for role, color in ((QPalette.Window, "#f0f0f0"),
                        (QPalette.Base, "#ffffff"),
                        (QPalette.Text, "#000000")):
        palette.setColor(role, QColor(color))
    qapp.setPalette(palette)
    view = ReportView()
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    yield view
    view.close()
    qapp.setStyle(old_style)
    qapp.setPalette(old_palette)
    qapp.setStyleSheet(old_qss)


@pytest.mark.parametrize("state", ["empty", "loading", "failed", "loaded", "cleared"])
def test_analysis_viewport_stays_dark(report_view, state):
    view = report_view
    view._analysis_panel.show()
    if state == "loading":
        view.set_analysis_loading(True)
    elif state == "failed":
        view._session_id = 7
        view._analysis_available = True
        view.set_analysis_loading(True)
        view._on_analysis_failed(7, "analyze", "analysis_timeout")
    elif state in {"loaded", "cleared"}:
        view.show_validated_analysis({"claims": [{"text": "有效分析结果。"}]})
        if state == "cleared":
            view.clear_analysis()
    QApplication.processEvents()
    image = view._analysis_scroll.viewport().grab().toImage()
    assert image.pixelColor(image.width() // 2, image.height() // 2).name() == PALETTE["background"]


@pytest.mark.parametrize("mode", ["walking", "running"])
def test_ground_report_html_has_dark_background_and_readable_text(report_view, mode):
    if mode == "walking":
        from tests.test_overground_walking import processor, walk, CONTACTS
        source = processor(8, stop_type="Software command")
        walk(source, CONTACTS, 2400)
    else:
        from tests.test_overground_running import processor, run, TRAJECTORY
        source = processor(8, starting_foot="Left")
        run(source, TRAJECTORY)
    report_view.load_report(source.build_report("manual", (), ()))
    report_view._tabs.setCurrentIndex(1)
    report_view._detail_tabs.setCurrentIndex(2)
    QApplication.processEvents()
    browser = report_view._step_page.findChild(QTextBrowser)
    assert "已识别脚印测量" in browser.toPlainText()
    image = browser.viewport().grab().toImage()
    # The document's inset stays empty even when a wide raw table scrolls horizontally.
    assert image.pixelColor(2, 2).name() == PALETTE["control"]
    assert browser.palette().color(QPalette.Text).name() == PALETTE["text"]


@pytest.mark.parametrize("attribute", ["_tabs", "_detail_tabs"])
def test_unused_report_tab_strip_does_not_draw_a_native_white_line(report_view, attribute):
    report_view._tabs.setCurrentIndex(1)
    QApplication.processEvents()
    bar = getattr(report_view, attribute).tabBar()
    image = bar.grab().toImage()
    # Document-mode tabs fill the row; its unused right edge has no text.
    assert all(max(image.pixelColor(image.width() - 4, y).getRgb()[:3]) < 100
               for y in range(image.height()))

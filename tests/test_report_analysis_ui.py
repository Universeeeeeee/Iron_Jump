"""UI contracts for the single validated smart-analysis area."""

from __future__ import annotations

import time

import pytest

from config.test_report import JumpTestReport
from ui.views.report_view import ReportView


def _report():
    return JumpTestReport(
        touch_count=1,
        lift_count=1,
        air_times=(0.4,),
        contact_times=(0.2,),
        cycle_times=(0.6,),
        avg_jump_height=0.2,
        max_jump_height=0.2,
        avg_air_time=0.4,
        max_air_time=0.4,
        avg_contact_time=0.2,
        avg_cadence=100.0,
        finish_reason="manual",
    )


class _FakeAnalysisClient:
    def __init__(self, *, latest=None, analyze=None, delay=0.0):
        self.latest = latest
        self.analyze = analyze or {
            "analysis": {
                "claims": [
                    {
                        "text": "后半程触地时间增加。",
                        "limitations": ["co_change_is_not_causation"],
                    }
                ],
                "overall_limitations": [],
            },
            "analysis_run_id": "run_1",
        }
        self.delay = delay
        self.latest_calls = []
        self.analyze_calls = []

    def get_latest_analysis(self, session_id, scope, timeout=5):
        self.latest_calls.append((session_id, scope))
        return self.latest

    def analyze_report(self, session_id, scope, timeout=120):
        self.analyze_calls.append((session_id, scope))
        if self.delay:
            time.sleep(self.delay)
        return self.analyze


def _wait_idle(qtbot, view):
    qtbot.waitUntil(
        lambda: not view._analysis_workers,
        timeout=2000,
    )


def test_entry_requires_ready_state_supported_report_and_persisted_session(qtbot):
    client = _FakeAnalysisClient()
    view = ReportView(llm_client=client)
    qtbot.addWidget(view)
    view.show()

    view.load_report(_report(), None)
    view.set_analysis_availability(True)
    assert view._analysis_panel.isHidden()

    view.load_report(_report(), 12)
    view.set_analysis_availability(False)
    assert view._analysis_panel.isHidden()

    view.set_analysis_availability(True)
    assert not view._analysis_panel.isHidden()
    _wait_idle(qtbot, view)
    assert client.latest_calls[0][0] == 12


def test_loading_report_reads_latest_but_never_starts_model_analysis(qtbot):
    client = _FakeAnalysisClient(
        latest={
            "claims": [{"text": "已保存的有效分析。", "limitations": []}],
            "overall_limitations": [],
        }
    )
    view = ReportView(llm_client=client)
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)

    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)

    assert len(client.latest_calls) == 1
    assert client.analyze_calls == []
    assert "已保存的有效分析" in view._analysis_result.text()
    assert view._analysis_button.text() == "重新分析"


def test_user_click_starts_one_analysis_and_displays_only_returned_validated_result(qtbot):
    client = _FakeAnalysisClient(delay=0.05)
    view = ReportView(llm_client=client)
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)

    view._analysis_button.click()
    view._analysis_button.click()
    _wait_idle(qtbot, view)

    assert len(client.analyze_calls) == 1
    assert "后半程触地时间增加" in view._analysis_result.text()
    assert "证据限制" in view._analysis_result.text()


def test_failed_analysis_never_displays_partial_draft(qtbot):
    client = _FakeAnalysisClient(
        analyze={
            "error_code": "unsupported_predicate",
            "draft": "不应展示的草稿",
        }
    )
    view = ReportView(llm_client=client)
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)

    view._analysis_button.click()
    _wait_idle(qtbot, view)

    assert "不应展示的草稿" not in view._analysis_result.text()
    assert view._analysis_result.isHidden()
    assert "未能生成通过验证的结果" in view._analysis_status.text()


@pytest.mark.parametrize(
    "error_code,expected",
    (
        ("analysis_timeout", "超过服务端时间限制"),
        ("analysis_client_timeout", "未在预期时间内响应"),
    ),
)
def test_timeout_errors_have_specific_messages(qtbot, error_code, expected):
    client = _FakeAnalysisClient(analyze={"error_code": error_code})
    view = ReportView(llm_client=client)
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)

    view._analysis_button.click()
    _wait_idle(qtbot, view)

    assert expected in view._analysis_status.text()
    assert view._analysis_result.isHidden()


def test_switching_report_clears_previous_analysis(qtbot):
    client = _FakeAnalysisClient(
        latest={
            "claims": [{"text": "旧会话结果。", "limitations": []}],
            "overall_limitations": [],
        }
    )
    view = ReportView(llm_client=client)
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)
    assert "旧会话结果" in view._analysis_result.text()

    client.latest = None
    view.load_report(_report(), 13)
    _wait_idle(qtbot, view)

    assert view._analysis_result.isHidden()
    assert view._session_id == 13


def test_schema_v4_recommendations_render_only_validated_http_references(qtbot):
    view = ReportView(llm_client=_FakeAnalysisClient())
    qtbot.addWidget(view)
    view.show_validated_analysis(
        {
            "claims": [{"text": "可信结论。", "limitations": []}],
            "recommendations": [
                {
                    "text": "建议复核动作一致性。",
                    "citation_refs": ["cite-1"],
                    "limitations": ["仅用于一般复核"],
                }
            ],
            "references": [
                {
                    "citation_id": "cite-1",
                    "title": "Reviewed <Paper>",
                    "url": "https://example.org/paper",
                    "locator": "Methods ¶1",
                },
                {
                    "citation_id": "bad",
                    "title": "Unsafe",
                    "url": "javascript:alert(1)",
                },
            ],
            "overall_limitations": [],
        }
    )

    rendered = view._analysis_result.text()
    assert "循证行动建议" in rendered
    assert "https://example.org/paper" in rendered
    assert "javascript:" not in rendered
    assert "Reviewed &lt;Paper&gt;" in rendered
    assert "建议限制：仅用于一般复核" in rendered


@pytest.mark.parametrize(
    "audit,expected",
    (
        (
            {"status": "degraded", "error_code": "retrieval_failed"},
            "循证建议暂时不可用",
        ),
        (
            {"status": "no_evidence"},
            "未检索到满足条件的文献证据",
        ),
    ),
)
def test_rag_audit_status_is_visible_to_user(qtbot, audit, expected):
    view = ReportView(llm_client=_FakeAnalysisClient())
    qtbot.addWidget(view)

    view.show_validated_analysis(
        {
            "claims": [{"text": "可信结论。", "limitations": []}],
            "recommendations": [],
            "references": [],
            "rag_audit": audit,
            "overall_limitations": [],
        }
    )

    assert expected in view._analysis_result.text()


def test_missing_rag_audit_does_not_show_degradation(qtbot):
    view = ReportView(llm_client=_FakeAnalysisClient())
    qtbot.addWidget(view)

    view.show_validated_analysis(
        {
            "claims": [{"text": "可信结论。", "limitations": []}],
            "recommendations": [],
            "references": [],
            "overall_limitations": [],
        }
    )

    assert "循证建议暂时不可用" not in view._analysis_result.text()

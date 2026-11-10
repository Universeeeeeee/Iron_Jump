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
    assert not view._analysis_entry.isHidden()
    assert view._analysis_panel.isHidden()
    view._analysis_entry.click()
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

    view._open_analysis()
    view._analysis_button.click()
    view._open_analysis()
    view._analysis_button.click()
    _wait_idle(qtbot, view)

    assert len(client.analyze_calls) == 1
    assert "后半程触地时间增加" in view._analysis_result.text()
    assert "证据限制" not in view._analysis_result.text()


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

    view._open_analysis()
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

    view._open_analysis()
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
            "文献建议生成暂时不可用",
        ),
        (
            {"status": "no_evidence"},
            "本次未检索到匹配的建议文献",
        ),
        (
            {"status": "no_evidence", "error_code": "no_supported_query"},
            "当前指标暂无匹配的建议文献",
        ),
        (
            {"status": "degraded", "error_code": "planning_failed"},
            "文献建议生成暂时不可用",
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
    assert "可信结论。" in view._analysis_result.text()


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


def test_long_analysis_does_not_shrink_report_and_can_be_closed(qtbot):
    view = ReportView(llm_client=_FakeAnalysisClient())
    qtbot.addWidget(view)
    view.resize(1100, 760)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)
    before = view._tabs.geometry()
    view._analysis_entry.click()
    view.show_validated_analysis({"claims": [{"text": "长分析结果。" * 40, "limitations": []} for _ in range(80)]})
    qtbot.waitUntil(lambda: view._analysis_scroll.verticalScrollBar().maximum() > 0)
    assert view._tabs.geometry() == before
    assert view._analysis_close_button.isVisible()
    view._analysis_close_button.click()
    assert view._analysis_panel.isHidden()
    assert view._tabs.geometry() == before
    view._analysis_entry.click()
    assert not view._analysis_panel.isHidden()
    assert "长分析结果" in view._analysis_result.text()
    view._analysis_panel.reject()
    assert view._analysis_panel.isHidden()


def test_close_during_analysis_is_not_undone_by_late_result(qtbot):
    view = ReportView(llm_client=_FakeAnalysisClient(delay=.1))
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)
    view._analysis_entry.click()
    view._analysis_button.click()
    view._analysis_close_button.click()
    assert view._analysis_panel.isHidden()
    _wait_idle(qtbot, view)
    assert view._analysis_panel.isHidden()
    assert "后半程触地时间增加" in view._analysis_result.text()


def test_leaving_or_switching_report_closes_analysis_window(qtbot):
    view = ReportView(llm_client=_FakeAnalysisClient())
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    _wait_idle(qtbot, view)
    view._analysis_entry.click()
    view.load_report(_report(), 13)
    assert view._analysis_panel.isHidden()
    _wait_idle(qtbot, view)
    view._analysis_entry.click()
    view.hide()
    assert view._analysis_panel.isHidden()


def _saved_analysis(run_id="base-1", text="完整报告发现", *, question=None):
    return {
        "analysis_run_id": run_id,
        "summary": text,
        "claims": [{"claim_id": "c1", "text": text, "evidence_refs": ["e1"], "limitations": []}],
        "evidence": [{
            "package_id": "package-1",
            "package_digest": "digest-1",
            "items": [{
                "evidence_id": "e1", "node_id": "node-1", "question_id": "question-1",
                "tool_name": "analyze_current_session", "analysis_method": "descriptive_summary",
                "record_set_id": "jumps", "record_refs": ["jump-0"], "predicates": [],
                "tool_run_id": "tool-1", "provenance_id": "provenance-1",
            }],
            "tool_runs": [], "provenance": [],
        }],
        "presentation": {"insight_cards": [{"claim_id": "c1", "title": text}], "charts": []},
        "question_context": {"question": question, "selection_label": "后半有效记录"} if question else None,
    }


class _FollowupClient(_FakeAnalysisClient):
    def __init__(self, *, delay=0, latest_delay=0, error=None, message=""):
        super().__init__(latest=_saved_analysis())
        self.ask_calls = []
        self.ask_delay = delay
        self.latest_delay = latest_delay
        self.error = error
        self.message = message

    def get_latest_analysis(self, session_id, scope, timeout=5):
        payload = super().get_latest_analysis(session_id, scope, timeout)
        if self.latest_delay:
            time.sleep(self.latest_delay)
        return payload

    def ask_report(self, session_id, scope, question, **context):
        self.ask_calls.append({"session_id": session_id, "scope": scope, "question": question, **context})
        run_id = f"ask-{len(self.ask_calls)}"
        if self.ask_delay:
            time.sleep(self.ask_delay)
        if self.error:
            return {"error_code": self.error, "message": self.message}
        return {"analysis": _saved_analysis(run_id, f"回答{len(self.ask_calls)}", question=question), "analysis_run_id": run_id}


def _followup_view(qtbot, client):
    view = ReportView(llm_client=client)
    qtbot.addWidget(view)
    view.show()
    view.set_analysis_availability(True)
    view.load_report(_report(), 12)
    return view


def test_followup_uses_selected_claim_then_current_answer_as_parent(qtbot):
    client = _FollowupClient(delay=.05)
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    original_headline = view._analysis_headline.text()
    view._analysis_entry.click()
    view._followup_target.setCurrentIndex(1)
    view._followup_question.setText("只看后半程")
    view._followup_send.click()
    view._followup_send.click()
    view._analysis_close_button.click()
    _wait_idle(qtbot, view)
    assert len(client.ask_calls) == 1
    assert client.ask_calls[0]["parent_analysis_run_id"] == "base-1"
    assert client.ask_calls[0]["selected_claim_id"] == "c1"
    assert view._analysis_headline.text() == original_headline
    assert view._analysis_panel.isHidden()
    assert view._analysis_data["analysis_run_id"] == "ask-1"
    assert view._followup_target.currentText() == "继续当前分析"
    assert "只看后半程" in view._analysis_result.text()
    assert "后半有效记录" in view._analysis_result.text()
    view._analysis_entry.click()
    view._followup_question.setText("再看左侧")
    view._followup_send.click()
    _wait_idle(qtbot, view)
    assert client.ask_calls[1]["parent_analysis_run_id"] == "ask-1"
    view._analysis_default_button.click()
    assert view._analysis_data["analysis_run_id"] == "base-1"
    assert view._followup_target.currentText() == "整体报告"
    assert "完整报告发现" in view._analysis_result.text()
    assert "本次提问" not in view._analysis_result.text()


class _HistoryClient(_FollowupClient):
    def __init__(self):
        super().__init__()
        self.saved = {
            "earlier": _saved_analysis("earlier", "历史后半程回答", question="只看后半程"),
            "recent": _saved_analysis("recent", "历史左侧回答", question="其中左侧呢"),
        }
        self.saved_calls = []
        self.fail_saved = False
        self.saved_delay = 0

    def get_analysis_history(self, session_id, scope):
        if session_id != 12:
            return {"history": []}
        return {"history": [
            {"analysis_run_id": run_id, "created_at": "2026-11-10 12:00", "question": question}
            for run_id, question in (("recent", "其中左侧呢"), ("earlier", "只看后半程"), ("base-1", ""))
        ]}

    def get_saved_analysis(self, session_id, scope, analysis_run_id):
        self.saved_calls.append(analysis_run_id)
        if self.saved_delay:
            time.sleep(self.saved_delay)
        if self.fail_saved:
            return {"error_code": "invalid_parent_analysis"}
        return {"analysis": self.saved[analysis_run_id]}


def test_reopening_report_restores_history_and_selected_answer_becomes_parent(qtbot):
    client = _HistoryClient()
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    assert view._analysis_data["analysis_run_id"] == "recent"
    assert view._default_analysis_data["analysis_run_id"] == "base-1"
    view._analysis_history.setCurrentIndex(view._analysis_history.findData("earlier"))
    _wait_idle(qtbot, view)
    assert "历史后半程回答" in view._analysis_result.text()
    view._followup_question.setText("其中右侧呢")
    view._followup_send.click()
    _wait_idle(qtbot, view)
    assert client.ask_calls[-1]["parent_analysis_run_id"] == "earlier"
    view._show_default_analysis()
    assert view._analysis_data["analysis_run_id"] == "base-1"
    view._analysis_history.setCurrentIndex(view._analysis_history.findData("earlier"))
    assert client.saved_calls == ["recent", "earlier"]
    assert view._analysis_data["analysis_run_id"] == "earlier"
    view.clear_analysis()
    assert view._analysis_history.count() == 0
    assert view._saved_analyses == {}


def test_failed_history_selection_keeps_display_and_selector_consistent(qtbot):
    client = _HistoryClient()
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    client.fail_saved = True
    view._analysis_history.setCurrentIndex(view._analysis_history.findData("earlier"))
    _wait_idle(qtbot, view)
    assert view._analysis_data["analysis_run_id"] == "recent"
    assert view._analysis_history.currentData() == "recent"
    assert not view._analysis_busy


def test_late_saved_answer_cannot_replace_another_report(qtbot):
    client = _HistoryClient()
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    client.saved_delay = .15
    view._analysis_history.setCurrentIndex(view._analysis_history.findData("earlier"))
    qtbot.waitUntil(lambda: "earlier" in client.saved_calls)
    client.latest = _saved_analysis("other-report", "另一份报告")
    view.load_report(_report(), 13)
    _wait_idle(qtbot, view)
    assert view._analysis_data["analysis_run_id"] == "other-report"
    assert "earlier" not in view._saved_analyses
    assert view._analysis_history.findData("earlier") == -1


@pytest.mark.parametrize("references,records", [
    ([], ["jump-0"]),
    (["missing"], ["jump-0"]),
    (["e1", "missing"], ["jump-0"]),
    (["e1"], []),
])
def test_followup_claim_choices_require_resolvable_record_evidence(qtbot, references, records):
    client = _FollowupClient()
    client.latest["claims"][0]["evidence_refs"] = references
    client.latest["evidence"][0]["items"][0]["record_refs"] = records
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    assert view._followup_target.count() == 1
    assert view._followup_target.currentData() is None
    view._followup_question.setText("查看触地时间")
    assert view._followup_send.isEnabled()


@pytest.mark.parametrize("next_session", [12, 13])
def test_late_followup_cannot_replace_reloaded_report(qtbot, next_session):
    client = _FollowupClient(delay=.15)
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    view._followup_question.setText("只看后半程")
    view._followup_send.click()
    qtbot.waitUntil(lambda: len(client.ask_calls) == 1)
    client.latest = _saved_analysis("replacement", "重新加载的报告")
    view.load_report(_report(), next_session)
    _wait_idle(qtbot, view)
    assert view._analysis_data["analysis_run_id"] == "replacement"
    assert "回答1" not in view._analysis_result.text()
    assert "本次提问" not in view._analysis_result.text()
    assert not view._analysis_busy


def test_late_latest_does_not_overwrite_answer_to_first_question(qtbot):
    client = _FollowupClient(latest_delay=.15)
    view = _followup_view(qtbot, client)
    view._followup_question.setText("查看触地时间")
    view._followup_send.click()
    _wait_idle(qtbot, view)
    assert view._analysis_data["analysis_run_id"] == "ask-1"
    assert client.ask_calls[0]["parent_analysis_run_id"] is None


def test_failed_followup_preserves_answer_and_can_be_retried(qtbot):
    client = _FollowupClient(error="analysis_client_timeout")
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    view._followup_question.setText("   ")
    view._followup_send.click()
    assert client.ask_calls == []
    view._followup_question.setText("只看后半程")
    view._followup_send.click()
    _wait_idle(qtbot, view)
    assert view._analysis_data["analysis_run_id"] == "base-1"
    assert view._followup_question.text() == "只看后半程"
    assert view._followup_send.isEnabled()
    assert "预期时间内响应" in view._analysis_status.text()


def test_followup_clarification_displays_specific_question_as_plain_text(qtbot):
    from PySide6.QtCore import Qt

    clarification = "请选择触地时间或腾空时间，并指定 <范围>。"
    client = _FollowupClient(error="question_needs_clarification", message=clarification)
    view = _followup_view(qtbot, client)
    _wait_idle(qtbot, view)
    view._followup_question.setText("分析时间")
    view._followup_send.click()
    _wait_idle(qtbot, view)
    assert view._analysis_status.text() == clarification
    assert view._analysis_status.textFormat() == Qt.PlainText
    assert view._followup_question.text() == "分析时间"
    assert view._followup_question.isEnabled()
    assert view._analysis_data["analysis_run_id"] == "base-1"

"""Regression tests for AgentConfigPanel request lifecycle handling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtGui import QPalette, QTextCursor
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QApplication, QFrame, QScrollArea

from config.treadmill_config import TreadmillGaitConfig
from ui.views.agent_config_panel import AgentConfigPanel, _LLMHttpWorker


_APP = None


def _app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    else:
        _APP = app
    return _APP


class _FakeClient:
    is_running = True

    def start(self):
        return True

    def worker_status(self, timeout=0.25):
        return "ready"

    def chat(self, message, athlete, agent_mode="jump"):
        return {"reply": f"reply: {message}"}

    def reset(self):
        pass


class _RestartingClient:
    is_running = True

    def __init__(self):
        self.status_calls = []
        self.chat_calls = []

    def start(self):
        return True

    def worker_status(self, timeout=0.25):
        self.status_calls.append(timeout)
        return "starting"

    def chat(self, message, athlete, agent_mode="jump"):
        self.chat_calls.append(message)
        return {"error": "worker 未启动"}


class _RestartableClient(_FakeClient):
    def __init__(self):
        self.is_running = False
        self.start_calls = 0

    def start(self):
        self.start_calls += 1
        self.is_running = True
        return True


class _BusyWorker:
    _agent_mode = "jump"

    @staticmethod
    def isRunning():
        return True


class _ModeCapturingClient:
    is_running = True

    def __init__(self):
        self.chat_calls = []

    def start(self):
        return True

    def worker_status(self, timeout=0.25):
        return "ready"

    def chat(self, message, athlete, agent_mode="jump"):
        self.chat_calls.append(
            {"message": message, "athlete": athlete, "agent_mode": agent_mode}
        )
        return {"reply": f"reply: {message}"}

    def reset(self):
        pass


class _TreadmillConfigClient(_ModeCapturingClient):
    def chat(self, message, athlete, agent_mode="jump"):
        self.chat_calls.append(
            {"message": message, "athlete": athlete, "agent_mode": agent_mode}
        )
        return {
            "reply": "configured",
            "config": {
                "test_type": "Treadmill Gait Test",
                "stop_type": "Software command",
                "test_length": None,
                "treadmill_speed": 5.5,
                "direction": "Interface side",
            },
        }

    def reset(self):
        pass


class AgentConfigPanelRequestLifecycleTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.panel = AgentConfigPanel(llm_client=_FakeClient())
        self.panel._worker_ready = True
        self.panel._sync_mode_state()

    def _make_stale_worker(self):
        worker = _LLMHttpWorker(
            self.panel._llm_client,
            "old request",
            self.panel._current_athlete_profile(),
            request_id=1,
        )
        self.panel._llm_worker = worker
        self.panel._active_request_id = 2
        return worker

    def _send_and_finish(self, message: str, reply: str) -> None:
        self.panel._chat_input.setText(message)
        original_start = _LLMHttpWorker.start
        _LLMHttpWorker.start = lambda self: None
        try:
            self.panel._on_send_message()
        finally:
            _LLMHttpWorker.start = original_start

        worker = self.panel._llm_worker
        self.assertIsNotNone(worker)
        worker.finished.emit(None, reply)

    def test_reply_is_appended_after_current_user_when_cursor_is_in_old_reply(self):
        self._send_and_finish(
            "第一问",
            "第一条 **回答**\n\n- 项目甲\n- 项目乙",
        )
        first_plain_text = self.panel._chat_display.toPlainText()
        old_reply_end = first_plain_text.index("第一条 回答") + len("第一条 回答")
        cursor = self.panel._chat_display.textCursor()
        cursor.setPosition(old_reply_end)
        self.panel._chat_display.setTextCursor(cursor)

        self._send_and_finish(
            "第二问",
            "第二条 **回答**\n\n- 项目丙\n- 项目丁",
        )

        plain_text = self.panel._chat_display.toPlainText()
        self.assertIn("AI: 第二条 回答", plain_text)
        expected_order = (
            plain_text.index("你: 第一问"),
            plain_text.index("AI: 第一条 回答"),
            plain_text.index("你: 第二问"),
            plain_text.index("AI: 第二条 回答"),
        )
        self.assertEqual(expected_order, tuple(sorted(expected_order)))
        self.assertEqual(plain_text.count("第一条 回答"), 1)
        self.assertEqual(plain_text.count("第二条 回答"), 1)
        self.assertIn("项目丙", plain_text)
        self.assertIn("项目丁", plain_text)
        bold_cursor = self.panel._chat_display.document().find("回答")
        self.assertGreater(bold_cursor.charFormat().fontWeight(), 400)
        list_cursor = self.panel._chat_display.document().find("项目丙")
        self.assertIsNotNone(list_cursor.block().textList())

    def test_reply_does_not_replace_selection_in_old_reply(self):
        self._send_and_finish("第一问", "必须保留这段文字")
        plain_text = self.panel._chat_display.toPlainText()
        selection_start = plain_text.index("这段")
        cursor = self.panel._chat_display.textCursor()
        cursor.setPosition(selection_start)
        cursor.setPosition(selection_start + len("这段"), QTextCursor.KeepAnchor)
        self.panel._chat_display.setTextCursor(cursor)

        self._send_and_finish("第二问", "新的回答")

        plain_text = self.panel._chat_display.toPlainText()
        self.assertIn("必须保留这段文字", plain_text)
        self.assertIn("你: 第二问\nAI: 新的回答", plain_text)
        self.assertEqual(
            self.panel._chat_display.textCursor().selectedText(),
            "这段",
        )

    def test_user_message_is_rendered_as_text_not_html(self):
        self._send_and_finish("<b>普通文字</b>", "收到")

        self.assertIn(
            "你: <b>普通文字</b>",
            self.panel._chat_display.toPlainText(),
        )

    def test_chat_follows_new_entries_when_view_was_at_bottom(self):
        self.panel._chat_display.setFixedSize(320, 100)
        self.panel.show()
        QApplication.processEvents()
        long_reply = "\n\n".join(f"第 {index} 段" for index in range(30))
        self._send_and_finish("第一问", long_reply)
        QApplication.processEvents()
        scrollbar = self.panel._chat_display.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(scrollbar.maximum())

        self._send_and_finish("第二问", long_reply)
        QApplication.processEvents()

        self.assertEqual(scrollbar.value(), scrollbar.maximum())

    def test_chat_keeps_scroll_position_when_user_scrolled_up(self):
        self.panel._chat_display.setFixedSize(320, 100)
        self.panel.show()
        QApplication.processEvents()
        long_reply = "\n\n".join(f"第 {index} 段" for index in range(30))
        self._send_and_finish("第一问", long_reply)
        QApplication.processEvents()
        scrollbar = self.panel._chat_display.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(0)

        self._send_and_finish("第二问", long_reply)
        QApplication.processEvents()

        self.assertEqual(scrollbar.value(), 0)

    def test_stale_finished_signal_clears_worker_reference(self):
        worker = self._make_stale_worker()
        worker.finished.connect(self.panel._on_llm_finished)

        worker.finished.emit(None, "old reply")

        self.assertIsNone(self.panel._llm_worker)
        self.assertEqual(self.panel._chat_display.toPlainText(), "")
        self.assertTrue(self.panel._chat_input.isEnabled())

    def test_stale_error_signal_clears_worker_reference(self):
        worker = self._make_stale_worker()
        worker.error.connect(self.panel._on_llm_error)

        worker.error.emit("old error")

        self.assertIsNone(self.panel._llm_worker)
        self.assertEqual(self.panel._chat_display.toPlainText(), "")
        self.assertTrue(self.panel._chat_input.isEnabled())

    def test_send_rechecks_worker_status_before_starting_http_worker(self):
        client = _RestartingClient()
        panel = AgentConfigPanel(llm_client=client)
        panel._worker_ready = True
        panel._sync_mode_state()
        panel._chat_input.setText("入门用户 3 次纵跳")

        panel._on_send_message()

        self.assertEqual(client.chat_calls, [])
        self.assertIsNone(panel._llm_worker)
        self.assertFalse(panel._worker_ready)
        self.assertNotIn("worker 未启动", panel._chat_display.toPlainText())
        self.assertIn("初始化", panel._status_label.text())

    def test_agent_panel_sends_treadmill_gait_agent_mode(self):
        client = _ModeCapturingClient()
        panel = AgentConfigPanel(llm_client=client)
        panel._worker_ready = True
        panel._sync_mode_state()
        panel._test_type_combo.setCurrentText("Treadmill Gait Test")
        panel._chat_input.setText("帮我配置跑步机步态测试")
        original_start = _LLMHttpWorker.start
        _LLMHttpWorker.start = lambda self: None
        try:
            panel._on_send_message()
        finally:
            _LLMHttpWorker.start = original_start

        self.assertIsNotNone(panel._llm_worker)
        self.assertEqual(panel._llm_worker._agent_mode, "treadmill_gait")

    def test_switching_test_type_uses_independent_visible_conversations(self):
        self._send_and_finish("纵跳问题", "纵跳回答")

        self.panel._test_type_combo.setCurrentText("Treadmill Gait Test")

        self.assertEqual(self.panel._chat_display.toPlainText(), "")
        self.assertFalse(self.panel._prompt_chips.isHidden())

        self._send_and_finish("步态问题", "步态回答")
        self.panel._test_type_combo.setCurrentText("Jump Test")

        jump_text = self.panel._chat_display.toPlainText()
        self.assertIn("纵跳问题", jump_text)
        self.assertIn("纵跳回答", jump_text)
        self.assertNotIn("步态问题", jump_text)

        self.panel._test_type_combo.setCurrentText("Treadmill Gait Test")

        gait_text = self.panel._chat_display.toPlainText()
        self.assertIn("步态问题", gait_text)
        self.assertIn("步态回答", gait_text)
        self.assertNotIn("纵跳问题", gait_text)

    def test_reply_after_mode_switch_is_written_to_originating_conversation(self):
        self.panel._chat_input.setText("纵跳问题")
        original_start = _LLMHttpWorker.start
        _LLMHttpWorker.start = lambda self: None
        try:
            self.panel._on_send_message()
        finally:
            _LLMHttpWorker.start = original_start
        worker = self.panel._llm_worker

        self.panel._test_type_combo.setCurrentText("Treadmill Gait Test")
        worker.finished.emit(None, "迟到的纵跳回答")

        self.assertEqual(self.panel._chat_display.toPlainText(), "")

        self.panel._test_type_combo.setCurrentText("Jump Test")

        self.assertIn("迟到的纵跳回答", self.panel._chat_display.toPlainText())

    def test_mode_switch_allows_typing_while_another_request_is_busy(self):
        self.panel._llm_worker = _BusyWorker()
        self.panel._chat_input.setEnabled(False)
        self.panel.show()

        self.panel._test_type_combo.setCurrentText("Treadmill Gait Test")
        QApplication.processEvents()

        self.assertTrue(self.panel._chat_input.isEnabled())
        self.assertFalse(self.panel._send_btn.isEnabled())
        self.panel._chat_input.setFocus()
        QTest.keyClicks(self.panel._chat_input, "next request")
        self.assertEqual(self.panel._chat_input.text(), "next request")
        self.panel._on_send_message()
        self.assertEqual(self.panel._chat_input.text(), "next request")

    def test_mode_switch_restarts_a_stopped_worker(self):
        client = _RestartableClient()
        panel = AgentConfigPanel(llm_client=client)
        panel._worker_ready = True

        panel._test_type_combo.setCurrentText("Treadmill Gait Test")

        self.assertEqual(client.start_calls, 1)
        self.assertTrue(panel._chat_input.isEnabled())
        self.assertTrue(panel._send_btn.isEnabled())

    def test_reset_clears_all_mode_documents_to_match_worker_reset(self):
        self._send_and_finish("纵跳问题", "纵跳回答")
        self.panel._test_type_combo.setCurrentText("Treadmill Gait Test")
        self._send_and_finish("步态问题", "步态回答")

        self.panel._on_reset_chat()

        for document in self.panel._chat_documents.values():
            self.assertTrue(document.isEmpty())

    def test_llm_worker_deserializes_treadmill_config_with_config_from_dict(self):
        client = _TreadmillConfigClient()
        worker = _LLMHttpWorker(
            client,
            "帮我配置跑步机步态测试",
            self.panel._current_athlete_profile(),
            agent_mode="treadmill_gait",
        )
        finished = []
        worker.finished.connect(lambda config, reply: finished.append((config, reply)))

        worker.run()

        self.assertEqual(client.chat_calls[0]["agent_mode"], "treadmill_gait")
        self.assertIsInstance(finished[0][0], TreadmillGaitConfig)
        self.assertEqual(finished[0][0].treadmill_speed, 5.5)

    def test_intelligent_config_hides_provider_and_offline_controls(self):
        self.panel.resize(900, 600)
        self.panel.show()
        QApplication.processEvents()

        self.assertFalse(hasattr(self.panel, "_mode_combo"))
        self.assertFalse(hasattr(self.panel, "_offline_btn"))
        self.assertEqual(self.panel._assistant_title.text(), "配置助手")
        self.assertGreaterEqual(
            self.panel._assistant_title.width(),
            self.panel._assistant_title.sizeHint().width(),
        )
        self.assertTrue(self.panel._status_label.isHidden())

    def test_test_type_popup_uses_manual_config_dark_palette(self):
        self.panel.show()
        QApplication.processEvents()

        popup_palette = self.panel._test_type_combo.view().palette()

        self.assertEqual(popup_palette.color(QPalette.Text).name(), "#e7ebf2")
        self.assertEqual(popup_palette.color(QPalette.Base).name(), "#1a2230")

    def test_fullscreen_layout_prioritizes_assistant_and_flattens_cards(self):
        self.panel.resize(1220, 700)
        self.panel.show()
        QApplication.processEvents()

        self.assertLessEqual(self.panel._profile_card.width(), 230)
        self.assertTrue(self.panel._suggestion_card.isHidden())
        self.assertGreaterEqual(self.panel._chat_card.width(), 900)

        self.panel._on_offline_generate()
        QApplication.processEvents()

        self.assertTrue(self.panel._suggestion_card.isVisible())
        self.assertLessEqual(self.panel._suggestion_card.width(), 270)
        self.assertGreaterEqual(self.panel._chat_card.width(), 650)
        self.assertIn(
            "QFrame#AgentCard {\n  background-color: rgba(32, 37, 48, 0.72);\n"
            "  border: none;",
            self.panel.styleSheet(),
        )
        self.assertIn("QTextEdit {\n  border: none;", self.panel.styleSheet())

        suggestion_scroll = self.panel.findChild(
            QScrollArea, "SuggestionConfigScroll"
        )
        self.assertIsNotNone(suggestion_scroll)
        self.assertEqual(suggestion_scroll.frameShape(), QFrame.NoFrame)
        self.assertFalse(suggestion_scroll.isAncestorOf(self.panel._confirm_btn))

    def test_standard_width_keeps_assistant_full_height_and_uses_suggestion_drawer(self):
        self.panel.resize(900, 700)
        self.panel.show()
        QApplication.processEvents()

        self.assertTrue(self.panel._compact_layout)
        self.assertTrue(self.panel._suggestion_card.isHidden())
        self.assertGreaterEqual(self.panel._chat_card.width(), 620)
        self.assertEqual(self.panel._chat_card.height(), self.panel.height())

        self.panel._on_offline_generate()
        QApplication.processEvents()

        drawer = self.panel._suggestion_card
        self.assertTrue(drawer.isVisible())
        self.assertLessEqual(
            abs((drawer.x() + drawer.width()) - self.panel.width()),
            2,
        )
        self.assertEqual(drawer.height(), self.panel.height())

        self.panel._dismiss_suggestion_drawer()
        QApplication.processEvents()

        self.assertTrue(drawer.isHidden())
        self.assertTrue(self.panel._suggestion_toggle_btn.isVisible())

        self.panel._toggle_suggestion_drawer()
        QApplication.processEvents()

        self.assertTrue(drawer.isVisible())

    def test_prompt_shortcuts_yield_height_to_conversation_after_first_message(self):
        self.panel.resize(900, 700)
        self.panel.show()
        QApplication.processEvents()
        initial_height = self.panel._chat_display.height()

        self._send_and_finish("常规 5 次", "已生成建议")
        QApplication.processEvents()

        self.assertTrue(self.panel._prompt_chips.isHidden())
        self.assertGreater(self.panel._chat_display.height(), initial_height)

    def test_intelligent_config_reflows_without_clipping_at_narrow_width(self):
        self.panel.setFixedSize(620, 480)
        self.panel.show()
        QApplication.processEvents()

        self.assertTrue(self.panel._compact_layout)
        self.assertGreaterEqual(
            self.panel._assistant_title.width(),
            self.panel._assistant_title.sizeHint().width(),
        )
        for card in (
            self.panel._profile_card,
            self.panel._chat_card,
            self.panel._suggestion_card,
        ):
            self.assertTrue(self.panel.rect().contains(card.geometry()))

    def test_registered_age_is_read_only_but_temporary_age_is_editable(self):
        import tempfile

        from data.subject_store import SubjectStore

        with tempfile.TemporaryDirectory() as directory:
            store = SubjectStore(Path(directory) / "subjects.sqlite3")
            subject_id = store.create_subject("Alice", 1990)
            result = store.search_subjects("Alice")[0]
            panel = AgentConfigPanel(subject_store=store)

            panel.set_subject_result(result)

            self.assertEqual(result.subject.id, subject_id)
            self.assertFalse(panel._age_spin.isEnabled())

            panel.set_subject_result(None)

            self.assertTrue(panel._age_spin.isEnabled())

    def test_registered_age_is_read_only_without_a_profile_store(self):
        import tempfile

        from data.subject_store import SubjectStore

        with tempfile.TemporaryDirectory() as directory:
            store = SubjectStore(Path(directory) / "subjects.sqlite3")
            store.create_subject("Alice", 1990)
            result = store.search_subjects("Alice")[0]
            panel = AgentConfigPanel()

            panel.set_subject_result(result)

            self.assertFalse(panel._age_spin.isEnabled())


if __name__ == "__main__":
    unittest.main()

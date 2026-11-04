"""A result signal must not release a QThread that is still returning from run."""
import pytest
from qtpy.QtCore import QThread
from ui.views.agent_config_panel import AgentConfigPanel,_LLMHttpWorker
from tests.test_agent_config_panel import _FakeClient

@pytest.mark.parametrize('error',[False,True])
def test_result_waits_for_actual_thread_exit_before_releasing(qtbot,error):
    class LateReturnWorker(_LLMHttpWorker):
        tail_returned=False
        def run(self):
            if error:self.error.emit('injected error')
            else:self.finished.emit(None,'test reply')
            QThread.msleep(150)
            self.tail_returned=True
    panel=AgentConfigPanel(llm_client=_FakeClient());qtbot.addWidget(panel)
    panel._startup_timer.stop();panel._active_request_id=1
    worker=LateReturnWorker(panel._llm_client,'test',panel._current_athlete_profile(),request_id=1)
    worker.mode_revision=panel._mode_revision;panel._llm_worker=worker
    worker.finished.connect(panel._on_llm_finished);worker.error.connect(panel._on_llm_error)
    worker.start()
    try:
        qtbot.waitUntil(lambda:panel._llm_worker is None,timeout=3000)
        assert worker.tail_returned and not worker.isRunning()
    finally:worker.wait(3000)

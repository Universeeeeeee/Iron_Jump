"""Run the gait workflow without USB hardware: python -m ui.demo."""

from dataclasses import replace
from pathlib import Path
import sys

from qtpy.QtWidgets import QLabel, QMessageBox
from dayu_widgets.qt import application

from config.treadmill_config import TreadmillGaitConfig
from data.subject_store import SubjectStore
from hardware.simulated_worker import SimulatedGaitWorker
from path_utils import get_base_dir
from ui.llm_client import AgentWorkerClient
from ui.main_window import MainWindow
from ui.session_controller import SessionController


class OfflineDemoClient(AgentWorkerClient):
    """Keep the demonstration entirely local, including report navigation."""

    configuration_enabled = False

    def __init__(self):
        super().__init__(python_exe="", worker_script="")

    def start(self):
        return False

    def worker_status(self, **_kwargs):
        return "offline"


class DemoSessionController(SessionController):
    def __init__(self):
        super().__init__(worker_factory=SimulatedGaitWorker)

    def _do_stop(self, reason):
        report = super()._do_stop(reason)
        if report is not None:
            report = replace(report, report_config_snapshot={
                **report.report_config_snapshot,
                "data_source": "simulation",
                "simulation_description": "固定足印的交替接触信号；非受试者实测数据",
            })
        return report


class DemoWindow(MainWindow):
    def __init__(self, *, db_path=None, enable_voice=False, enable_agent=False):
        super().__init__(
            controller=DemoSessionController(),
            subject_store=SubjectStore(db_path or Path(get_base_dir()) / "data" / "demo.sqlite3"),
            llm_client=(AgentWorkerClient(
                python_exe=sys.executable,
                worker_script=str(Path(__file__).resolve().parents[1] / "agent" / "worker.py"),
            ) if enable_agent else OfflineDemoClient()),
            enable_background_checks=False,
        )
        self.setWindowTitle("Iron Jump · 步态演示（模拟数据）")
        label = QLabel("演示 · 模拟数据 · 独立数据库 · 请选择跑步机步态测试")
        label.setStyleSheet("color: #ffbb66; padding: 6px;")
        self.statusBar().addWidget(label, 1)
        self._voice_button.setEnabled(enable_voice)
        if not enable_voice:
            self._voice_button.setToolTip("此入口默认离线；统一配置后可通过 --voice 启用真实语音联调")
        self._setup_view.load_config_from_history(TreadmillGaitConfig(
            stop_type="Software command", test_length=None,
            treadmill_speed=3.6, direction="Interface side", starting_foot_override="left",
        ))
        panel = self._setup_view._agent_panel
        panel._test_type_combo.setCurrentIndex(panel._test_type_combo.findData("treadmill_gait"))
        self._setup_view._set_config_mode(0 if enable_agent else 1)
        self._setup_view._set_current_config(self._setup_view._current_config, "manual")

    def _on_ready(self, setup):
        if not isinstance(setup.config, TreadmillGaitConfig):
            QMessageBox.information(self, "步态演示", "此演示源仅支持跑步机步态测试，请切换测试类型。")
            return
        super()._on_ready(setup)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="模拟光栅的步态演示，使用独立数据库")
    parser.add_argument("--voice", action="store_true", help="允许手动开启真实 ASR/TTS（需配置密钥）")
    parser.add_argument("--agent", action="store_true", help="启用真实智能参数配置及报告分析服务")
    args = parser.parse_args()
    with application():
        window = DemoWindow(enable_voice=args.voice, enable_agent=args.agent)
        window.show()

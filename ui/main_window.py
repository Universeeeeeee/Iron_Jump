"""
main_window.py — 多视图主窗口

纯粹的视图路由器 + 全局事件处理。
硬件资源管理委托给 SessionController。

使用方式::

    python ui/main_window.py
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

# Ensure project root is importable when running `python ui/main_window.py`.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QMessageBox, QPushButton,
)
from dayu_widgets import dayu_theme
from dayu_widgets.qt import application

from config.test_config import TestConfig
from config.test_report import TestReport
from data.subject_store import SessionRecord, SubjectProfile, SubjectStore
from path_utils import get_base_dir
from ui.app_shell import (
    APP_DIALOG_QSS,
    MODULE_ATHLETES,
    MODULE_RESULTS,
    MODULE_SETTINGS,
    MODULE_TEST,
    ApplicationShell,
)
from ui.session_controller import SessionController
from ui.views.athletes_view import AthletesView
from ui.views.setup_view import SessionSetup, SetupView
from ui.views.execution_view import ExecutionView
from ui.views.history_view import HistoryView
from ui.views.report_view import ReportView
from ui.views.settings_view import SettingsView
from ui.llm_client import AgentWorkerClient

# Camera (可选)
try:
    from ui.camera import Camera
except ImportError:
    Camera = None

# 专用相机 widget + 检测工具
try:
    from camera.logi_camera import LogiCameraWidget
except ImportError:
    LogiCameraWidget = None

try:
    from camera.tinyse_camera import TinySeCameraControl, TinySeCameraWidget
except ImportError:
    TinySeCameraControl = None
    TinySeCameraWidget = None

try:
    from camera.tinyse_dshow_capture import TinySeDShowCapture
except ImportError:
    TinySeDShowCapture = None

import cv2
from qtpy.QtCore import QTimer


log = logging.getLogger(__name__)
_UNSET = object()


def _wallclock_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _apply_windows_dark_title_bar(
    window, *, platform_name: str | None = None, dwmapi=None
) -> bool:
    """Match the native Windows title bar to the application's dark UI."""
    if (platform_name or sys.platform) != "win32":
        return False

    try:
        import ctypes

        using_system_api = dwmapi is None
        if using_system_api:
            from ctypes import wintypes

            dwmapi = ctypes.windll.dwmapi

        setter = dwmapi.DwmSetWindowAttribute
        if using_system_api:
            setter.argtypes = [
                wintypes.HWND,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            setter.restype = wintypes.HRESULT

        hwnd = int(window.winId())

        def set_attribute(attribute: int, value: int) -> bool:
            native_value = ctypes.c_int(value)
            return (
                setter(
                    hwnd,
                    attribute,
                    ctypes.byref(native_value),
                    ctypes.sizeof(native_value),
                )
                == 0
            )

        dark_enabled = set_attribute(20, 1)
        if not dark_enabled:
            dark_enabled = set_attribute(19, 1)

        caption_colored = set_attribute(35, 0x0019110C)  # #0c1119
        set_attribute(36, 0x00FBF7F5)  # #f5f7fb
        return dark_enabled or caption_colored
    except Exception:
        log.debug("Windows dark title bar is unavailable", exc_info=True)
        return False


def _detect_tinyse_camera() -> bool:
    if TinySeCameraControl is not None:
        ctl = None
        try:
            ctl = TinySeCameraControl(0)
            return ctl.init()
        except Exception:
            log.exception("Tiny SE SDK 检测失败")
            return False
        finally:
            if ctl is not None:
                try:
                    ctl.close()
                except Exception:
                    log.exception("Tiny SE SDK 检测清理失败")

    if TinySeDShowCapture is None:
        return False

    try:
        probe = TinySeDShowCapture(device_needle="OBSBOT Tiny SE")
        probe.close()
        return True
    except Exception:
        log.exception("Tiny SE DirectShow 检测失败")
        return False


class MainWindow(QMainWindow):
    """
    多视图主窗口。

    职责:
      - 持有 QStackedWidget，管理 3 个 View 的切换
      - 持有 SessionController，委托硬件资源管理
      - 处理相机打开/关闭
      - 处理测试结束后的临时汇总 (Phase 5a, ReportView 在 5b 中加入)
    """

    def __init__(
        self,
        parent=None,
        *,
        subject_store=_UNSET,
        llm_client=_UNSET,
        controller=_UNSET,
        enable_background_checks: bool = True,
    ):
        super().__init__(parent)

        self.setStyleSheet(APP_DIALOG_QSS)
        app_icon = QIcon(
            os.path.join(
                get_base_dir(), "ui", "assets", "yingheng_app_icon.png"
            )
        )
        self.setWindowIcon(app_icon)
        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.setWindowIcon(app_icon)
        self.setWindowTitle("")
        _apply_windows_dark_title_bar(self)
        self.setMinimumSize(1180, 720)
        self.resize(1400, 820)
        self._enable_background_checks = enable_background_checks
        self._active_module = MODULE_TEST

        # ===== Controller =====
        self._controller = (
            SessionController(self) if controller is _UNSET else controller
        )

        if subject_store is _UNSET:
            try:
                self._subject_store: SubjectStore | None = SubjectStore()
            except Exception:
                log.exception("Failed to initialize subject store")
                self._subject_store = None
        else:
            self._subject_store = subject_store

        self._active_config: TestConfig | None = None
        self._subject_id: int | None = None
        self._subject: SubjectProfile | None = None
        self._subject_snapshot: dict | None = None
        self._team_id: int | None = None
        self._team_snapshot: dict | None = None
        self._config_source: str | None = None
        self._session_started_at: str | None = None
        self._last_session_id: int | None = None

        # ===== Views =====
        self._stack = QStackedWidget()

        if llm_client is _UNSET:
            self._llm_client = AgentWorkerClient(
                python_exe=sys.executable,
                worker_script=os.path.join(_project_root, "agent", "worker.py"),
            )
        else:
            self._llm_client = llm_client

        self._athletes_view = AthletesView(self._subject_store)
        self._setup_view = SetupView(subject_store=self._subject_store, llm_client=self._llm_client)
        self._exec_view = ExecutionView()
        self._report_view = ReportView(llm_client=self._llm_client)
        self._history_view = HistoryView(self._subject_store)
        self._settings_view = SettingsView(self._subject_store)

        self._stack.addWidget(self._athletes_view)
        self._stack.addWidget(self._setup_view)
        self._stack.addWidget(self._exec_view)
        self._stack.addWidget(self._report_view)
        self._stack.addWidget(self._history_view)
        self._stack.addWidget(self._settings_view)

        self._shell = ApplicationShell(self._stack)
        self.setCentralWidget(self._shell)
        self._voice = None
        self._voice_button = QPushButton("开启语音")
        self._voice_button.setObjectName("VoiceToggle")
        self._voice_button.setToolTip("豆包语音：配置、开始、暂停、继续、结束、分析报告")
        self._voice_button.clicked.connect(self._toggle_voice)
        self.statusBar().setStyleSheet(
            "QStatusBar { background: #0c1119; color: #aeb7c5; }"
            "QStatusBar::item { border: none; }"
            "QPushButton#VoiceToggle { background: #242e3c; color: #f2f5f9;"
            "border: 1px solid #354151; border-radius: 5px; padding: 5px 14px; }"
            "QPushButton#VoiceToggle:hover { border-color: #ff8a1f; }"
        )
        self.statusBar().addPermanentWidget(self._voice_button)

        # ===== Camera =====
        self._logi_camera = None
        self._tinyse_camera = None
        self._basic_camera = None

        # ===== 连接信号 =====
        self._connect_signals()

        # ===== 初始页面 =====
        self._go_to_setup()

        # ===== 异步检测相机设备 =====
        if self._enable_background_checks:
            QTimer.singleShot(0, self._detect_cameras)

        # ===== LLM Worker 健康检查 =====
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_llm_health)
        if self._enable_background_checks:
            self._health_timer.start(5000)
        self._health_fail_count = 0

    # ------------------------------------------------------------------
    #  信号连接
    # ------------------------------------------------------------------

    def _connect_signals(self):
        # Application shell → guarded module routing
        self._shell.module_requested.connect(self._request_module)

        # AthletesView → test/results modules
        self._athletes_view.test_requested.connect(self._on_athlete_test_requested)
        self._athletes_view.results_requested.connect(self._on_history_requested)
        self._athletes_view.team_results_requested.connect(
            self._on_team_history_requested
        )

        # SetupView → MainWindow
        self._setup_view.ready_signal.connect(self._on_ready)
        self._setup_view.history_requested.connect(self._on_history_requested)
        refresh_led_health = getattr(
            self._controller, "refresh_led_health", None
        )
        if callable(refresh_led_health):
            self._setup_view.led_health_refresh_requested.connect(
                refresh_led_health
            )

        # ExecutionView 控制 → MainWindow / Controller
        self._exec_view.start_requested.connect(self._on_start)
        self._exec_view.return_config_requested.connect(
            self._on_return_to_config
        )
        self._exec_view.pause_requested.connect(self._on_pause)
        self._exec_view.stop_requested.connect(self._on_manual_stop)
        self._exec_view.camera_requested.connect(self._on_camera)

        # Controller 实时数据 → ExecutionView (直连)
        self._controller.hop_event.connect(self._exec_view.on_hop_event)
        if hasattr(self._controller, "jump_quality_notice"):
            self._controller.jump_quality_notice.connect(
                self._exec_view.on_jump_quality_notice
            )
        self._controller.gait_step_event.connect(self._exec_view.on_gait_step_event)
        self._controller.gait_snapshot.connect(self._exec_view.on_gait_snapshot)
        self._controller.footprint_visual_frame.connect(
            self._exec_view.on_footprint_visual_frame
        )
        self._controller.device_message.connect(self._exec_view.on_device_message)
        self._controller.device_state_changed.connect(
            self._exec_view.on_device_state
        )
        self._controller.device_state_changed.connect(
            self._setup_view.on_device_state
        )
        if hasattr(self._controller, "led_health_changed"):
            self._controller.led_health_changed.connect(
                self._setup_view.on_led_health
            )
        self._setup_view.on_device_state(
            getattr(self._controller, "device_state", "disconnected"),
            "",
        )

        # Controller 生命周期 → MainWindow
        if hasattr(self._controller, "walking_readiness_changed"):
            self._controller.walking_readiness_changed.connect(self._exec_view.on_walking_readiness)
        self._controller.session_started.connect(self._exec_view.on_session_started)
        self._controller.session_started.connect(self._on_session_started)
        self._controller.session_finished.connect(self._on_session_finished)
        if hasattr(self._controller, "pause_state_changed"):
            self._controller.pause_state_changed.connect(self._exec_view.set_paused)

        # ReportView → MainWindow
        self._report_view.return_home.connect(self._go_to_setup)
        self._report_view.export_requested.connect(lambda: None)  # export handled internally

        # HistoryView → MainWindow
        self._history_view.return_setup.connect(self._go_to_setup)
        self._history_view.load_config_requested.connect(self._on_history_load_config)
        self._history_view.open_report_requested.connect(
            self._on_history_open_report
        )

    # ------------------------------------------------------------------
    #  视图切换
    # ------------------------------------------------------------------

    def _go_to_setup(self):
        self._set_active_module(MODULE_TEST)
        self._active_config = None
        self._subject_id = None
        self._subject = None
        self._subject_snapshot = None
        self._team_id = None
        self._team_snapshot = None
        self._config_source = None
        self._session_started_at = None
        self._setup_view.refresh_subjects()
        self._stack.setCurrentWidget(self._setup_view)
        ensure_device_connected = getattr(
            self._controller, "ensure_device_connected", None
        )
        if callable(ensure_device_connected):
            ensure_device_connected()

    def _go_to_execution(self):
        self._set_active_module(MODULE_TEST)
        self._stack.setCurrentWidget(self._exec_view)

    def _go_to_report(self):
        if not self._llm_client.is_running:
            self._llm_client.start()
        status = self._llm_client.worker_status(timeout=0.25)
        self._report_view.set_analysis_availability(status == "ready")
        self._set_active_module(MODULE_RESULTS)
        self._stack.setCurrentWidget(self._report_view)

    def _go_to_history(self):
        self._set_active_module(MODULE_RESULTS)
        self._stack.setCurrentWidget(self._history_view)

    def _go_to_athletes(self):
        self._athletes_view.refresh()
        self._set_active_module(MODULE_ATHLETES)
        self._stack.setCurrentWidget(self._athletes_view)

    def _go_to_settings(self):
        self._settings_view.refresh()
        self._set_active_module(MODULE_SETTINGS)
        self._stack.setCurrentWidget(self._settings_view)

    def _set_active_module(self, module: str) -> None:
        self._active_module = module
        self._shell.set_active_module(module)

    def _request_module(self, module: str) -> None:
        if module == self._active_module:
            return

        leaving_test = self._active_module == MODULE_TEST and module != MODULE_TEST
        if leaving_test and self._controller.is_running:
            answer = QMessageBox.question(
                self,
                "测试正在进行",
                "选择“是”将结束并保存当前结果；选择“中止”将结束并标记异常；"
                "选择“否”则留在测试。",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Abort,
                QMessageBox.No,
            )
            if answer == QMessageBox.No:
                self._shell.set_active_module(MODULE_TEST)
                return
            if answer == QMessageBox.Abort:
                self._controller.stop("error")
            else:
                self._controller.stop()
        elif leaving_test and self._stack.currentWidget() is self._exec_view:
            self._discard_prepared_session()

        if module == MODULE_ATHLETES:
            self._go_to_athletes()
        elif module == MODULE_TEST:
            self._go_to_setup()
        elif module == MODULE_RESULTS:
            self._history_view.load_all()
            self._go_to_history()
        elif module == MODULE_SETTINGS:
            self._go_to_settings()

    def _discard_prepared_session(self) -> None:
        discard = getattr(self._controller, "discard", None)
        if callable(discard):
            discard()
        self._exec_view.reset()
        self._active_config = None
        self._subject_id = None
        self._subject = None
        self._subject_snapshot = None
        self._team_id = None
        self._team_snapshot = None

    # ------------------------------------------------------------------
    #  事件处理
    # ------------------------------------------------------------------

    def _on_ready(self, setup: SessionSetup):
        """SetupView '准备就绪' → 初始化资源 + 切到 ExecutionView"""
        config = setup.config
        self._active_config = config
        self._subject_id = setup.subject_id
        self._subject = setup.subject
        self._subject_snapshot = setup.subject_snapshot or self._fallback_snapshot(
            setup.subject
        )
        self._team_id = setup.team_id
        self._team_snapshot = setup.team_snapshot
        self._config_source = setup.config_source
        self._session_started_at = None
        self._last_session_id = None
        self._exec_view.reset()
        self._exec_view.configure(config)
        self._controller.prepare(config)
        self._go_to_execution()

    def _on_history_requested(self, subject_result):
        self._history_view.load_subject(subject_result)
        self._go_to_history()

    def _on_team_history_requested(self, team):
        self._history_view.load_team(team)
        self._go_to_history()

    def _on_athlete_test_requested(self, subject_result):
        self._setup_view.select_subject(subject_result.subject.id)
        self._go_to_setup()

    def _on_history_load_config(self, config: TestConfig):
        self._setup_view.load_config_from_history(config)
        self._go_to_setup()

    def _on_history_open_report(self, session: SessionRecord) -> None:
        self._report_view.load_report(session.report, session.id)
        self._go_to_report()

    def _on_start(self):
        """ExecutionView '开始采集' → 启动 Controller"""
        if self._controller.device_state == "error":
            self._controller.retry_device()
            return
        self._controller.start()

    def _toggle_voice(self):
        if self._voice is None:
            from ui.voice_bridge import VoiceBridge
            self._voice = VoiceBridge(self)
        self._voice.toggle()

    def _on_return_to_config(self) -> None:
        if self._controller.is_running:
            return
        self._discard_prepared_session()
        self._go_to_setup()

    def _on_pause(self):
        """ExecutionView '暂停/继续' → 切换 Controller 暂停状态"""
        self._controller.toggle_pause()

    def _on_manual_stop(self):
        """ExecutionView '结束' → 手动停止"""
        self._controller.stop()

    def _on_session_started(self):
        self._session_started_at = _wallclock_now()

    def _on_session_finished(self, report: TestReport):
        """Controller 发来 TestReport → 切到 ReportView"""
        self._last_session_id = None
        if (
            self._subject_store is not None
            and self._active_config is not None
        ):
            try:
                snapshot = self._subject_snapshot or self._fallback_snapshot(
                    self._subject
                )
                self._last_session_id = self._subject_store.record_session(
                    self._subject_id,
                    self._active_config,
                    report,
                    started_at=self._session_started_at,
                    finished_at=_wallclock_now(),
                    height_cm=snapshot.get("height_cm"),
                    weight_kg=snapshot.get("weight_kg"),
                    subject_snapshot=snapshot,
                    config_source=self._config_source,
                    team_id=self._team_id,
                    team_snapshot=self._team_snapshot,
                )
            except Exception:
                log.exception("Failed to record subject session")

        self._report_view.load_report(report, self._last_session_id)
        self._go_to_report()

    @staticmethod
    def _fallback_snapshot(subject: SubjectProfile | None) -> dict:
        if subject is None:
            return {
                "display_name": "临时测试",
                "age": 30,
                "height_cm": 170.0,
                "weight_kg": 70.0,
                "level": "intermediate",
                "focus_side": "",
            }
        return {
            "display_name": subject.display_name,
            "age": max(0, datetime.now().year - subject.birth_year),
            "height_cm": subject.height_cm,
            "weight_kg": subject.weight_kg,
            "level": subject.level,
            "focus_side": subject.focus_side,
        }

    def _detect_cameras(self):
        """异步检测可用相机设备, 控制 Tiny SE 按钮显隐。"""
        self._exec_view.set_tinyse_available(_detect_tinyse_camera())

    def _check_llm_health(self):
        if not self._llm_client.is_running:
            self._report_view.set_analysis_availability(False)
            return
        status = self._llm_client.worker_status(timeout=0.25)
        self._report_view.set_analysis_availability(status == "ready")
        if status == "ready":
            self._health_fail_count = 0
        elif status in {"starting", "warming"}:
            return
        else:
            self._health_fail_count += 1
            if self._health_fail_count >= 2:
                log.warning("LLM worker health check failed twice, status=%s, stopping", status)
                self._llm_client.stop()
                self._health_fail_count = 0

    def _on_camera(self, camera_type: str):
        """根据 camera_type 打开/关闭对应相机窗口。
        
        支持三种类型: "logi" / "tinyse" / "basic"
        惰性创建, 已打开则置顶, 已销毁则重建。
        """
        if camera_type == "logi":
            if LogiCameraWidget is None:
                QMessageBox.warning(self, "相机", "LogiCameraWidget 模块不可用")
                return
            widget = self._logi_camera
            if widget is None:
                self._logi_camera = LogiCameraWidget()
                dayu_theme.apply(self._logi_camera)
                self._logi_camera.show()
            elif widget.isVisible():
                widget.raise_()
                widget.activateWindow()
                if widget.isMinimized():
                    widget.showNormal()
            else:
                # 已销毁则重建
                self._logi_camera = LogiCameraWidget()
                dayu_theme.apply(self._logi_camera)
                self._logi_camera.show()

        elif camera_type == "tinyse":
            if TinySeCameraWidget is None:
                QMessageBox.warning(self, "相机", "TinySeCameraWidget 模块不可用")
                return
            widget = self._tinyse_camera
            if widget is None:
                self._tinyse_camera = TinySeCameraWidget()
                dayu_theme.apply(self._tinyse_camera)
                self._tinyse_camera.show()
            elif widget.isVisible():
                widget.raise_()
                widget.activateWindow()
                if widget.isMinimized():
                    widget.showNormal()
            else:
                self._tinyse_camera = TinySeCameraWidget()
                dayu_theme.apply(self._tinyse_camera)
                self._tinyse_camera.show()

        elif camera_type == "basic":
            if Camera is None:
                QMessageBox.warning(self, "相机", "Camera 模块不可用")
                return
            cam = self._basic_camera
            if cam is None:
                cam = Camera()
                self._basic_camera = cam
            
            if not cam.is_running:
                cam.open_camera(threaded=True)
            else:
                cam.close_camera()
        else:
            log.warning(f"Unknown camera type: {camera_type}")

    # ------------------------------------------------------------------
    #  窗口关闭
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """关闭窗口时清理所有资源。"""
        if self._voice is not None:
            self._voice.close()
        # 停止测试会话
        if self._controller.is_running:
            self._controller.stop()
        else:
            discard = getattr(self._controller, "discard", None)
            if callable(discard):
                try:
                    discard()
                except Exception:
                    log.exception("Failed to discard prepared session on close")
        self._exec_view.reset()

        # 关闭相机
        try:
            if self._logi_camera is not None:
                self._logi_camera.close()
        except Exception:
            pass
        try:
            if self._tinyse_camera is not None:
                self._tinyse_camera.close()
        except Exception:
            pass
        try:
            if self._basic_camera is not None and self._basic_camera.is_running:
                self._basic_camera.close_camera()
        except Exception:
            pass

        # 关闭 LLM worker
        if self._llm_client.is_running:
            self._health_timer.stop()
            self._llm_client.stop()

        event.accept()


# ======================================================================
#  独立运行入口
# ======================================================================

if __name__ == "__main__":
    with application() as app:
        win = MainWindow()
        win.show()

        # 居中到屏幕 (防止 dayu_theme 导致窗口偏移到屏幕外)
        screen = app.primaryScreen().availableGeometry()
        win.move(
            (screen.width() - win.width()) // 2,
            (screen.height() - win.height()) // 2,
        )

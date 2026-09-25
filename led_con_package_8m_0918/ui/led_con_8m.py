"""
led_con_8m.py — 8m扩展版主界面 (8组LED面板: 1m..8m)

修改点 (相对3m版 led_con_3m.py):
  <<<8M-1>> 右侧从3个LEDPanel改为8个 (1m..8m各一个8x12面板, 2列×4行网格)
  <<<8M-2>> 连接 led_bits_8m_signal (8组96位)
  <<<8M-3>> 导出Excel从288列改为768列
  <<<8M-4>> 八米采集仅接受完整96字节帧，过滤长度异常和整帧全灭。
  <<<8M-5>> 物理线序默认 2m..8m、末组1m (与3m版线序规律一致),
            可用 DAYU_SEGMENT_ORDER 覆盖, 由worker解析。
  <<<FIX-1>> 抑制libpng iCCP警告 (在导入Qt之前设置环境变量)
"""
import os
import sys

# <<<FIX-1>> 抑制 libpng iCCP/sRGB 警告 (必须在导入 Qt 之前设置)
os.environ["QT_LOGGING_RULES"] = "qt.qpa.imageio.warning=false"
os.environ.setdefault("QT_IMAGEIO_MAXBPP", "32")

# 确保项目根目录可导入 (与3m版led_con_3m.py路径逻辑完全一致)
_module_dir = os.path.dirname(os.path.abspath(__file__))
if _module_dir not in sys.path:
    sys.path.insert(0, _module_dir)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from qtpy import QtWidgets
from qtpy.QtCore import QThread, Qt, QTimer
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets.qt import application
from dayu_widgets import dayu_theme
import time
from collections import deque

from openpyxl import Workbook

from hardware.receive import CyUsbInterfaceDevice, E_DATA_REPORT
from hardware.usb_worker_8m import UsbWorker
from hardware.capture_diagnostics import CaptureDiagnostics, LatestFrameMailbox
from ui.capture_archive import CaptureArchive
try:
    from .led_panel import LEDPanel
except ImportError:
    from led_panel import LEDPanel
from path_utils import find_dll as _find_dll, get_base_dir as _get_base_dir

NODE_COUNT_8M = 8
BITS_PER_NODE = 96
PANEL_GRID_COLUMNS = 2  # <<<8M-1>> 8面板按2列×4行布局


def _parse_int_env(name, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return default


class SerialDataWidget(QtWidgets.QWidget):
    """8m扩展版: 8组LED面板 (1m..8m各8x12)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dll_path = _find_dll()
        self.vid = _parse_int_env("DAYU_VID", 0x04B4)
        self.pid = _parse_int_env("DAYU_PID", 0x1004)
        self.timeout_ms = _parse_int_env("DAYU_TIMEOUT", 1)
        self.chunk_size = _parse_int_env("DAYU_CHUNK", 2048)
        self.serial_thread = None
        self.serial_worker = None
        self.paused = False
        self._display_mailbox = LatestFrameMailbox()
        self._diagnostics = None

        self._archive = CaptureArchive()
        self._export_frames = self._archive.frames
        self._export_timestamps = self._archive.timestamps
        self._export_start_time = None

        self._init_ui()
        self.setMinimumSize(1500, 800)
        self._frame_counter = 0
        self._last_hex = ""
        self._last_led_bits = [None] * NODE_COUNT_8M
        self._hex_log = deque(maxlen=10)
        self._led_dirty = False
        self._log_dirty = False
        self._ui_timer = QTimer(self)
        self._ui_timer.setTimerType(Qt.PreciseTimer)
        self._ui_timer.setInterval(16)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()

    def closeEvent(self, event):
        self._ui_timer.stop()
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        if self.serial_thread and self.serial_thread.isRunning():
            self.serial_thread.quit()
            self.serial_thread.wait(2000)
        self._archive.close()
        event.accept()

    def _init_ui(self):
        self.main_lay = QtWidgets.QHBoxLayout()

        # 左侧: 数据帧展示
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.addWidget(MDivider("数据展示"))
        self.text_edit = MTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setObjectName("data_display_edit")
        self.text_edit.setStyleSheet("QTextEdit#data_display_edit { font-size: 14pt; }")
        left_layout.addWidget(self.text_edit, 1)

        # 按钮区
        self.btn_container = QtWidgets.QWidget()
        self.btn_container.setMinimumHeight(60)
        self.btn_layout = QtWidgets.QHBoxLayout(self.btn_container)
        self.btn_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_start = MPushButton("开始测试").primary()
        self.btn_start.setMinimumHeight(60)
        self.btn_start.clicked.connect(self.on_start_clicked)
        self.btn_layout.addWidget(self.btn_start)
        left_layout.addWidget(self.btn_container, 0)

        # <<<8M-1>> 右侧: 8组LED面板 (2列×4行)
        right_layout = QtWidgets.QVBoxLayout()
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self.led_panels = []
        for node in range(NODE_COUNT_8M):
            segment = node + 1
            row = node // PANEL_GRID_COLUMNS
            col = node % PANEL_GRID_COLUMNS
            cell = QtWidgets.QVBoxLayout()
            cell.addWidget(MDivider(f"{segment}m LED面板 (96)"))
            panel = LEDPanel(rows=8, cols=12, parent=self)
            cell.addWidget(panel, 1)
            self.led_panels.append(panel)
            holder = QtWidgets.QWidget()
            holder.setLayout(cell)
            grid.addWidget(holder, row, col)
        right_layout.addLayout(grid)
        self.led_panel_1m = self.led_panels[0]  # 兼容命名习惯

        self.main_lay.addLayout(left_layout, 1)
        self.main_lay.addLayout(right_layout, 2)
        self.setLayout(self.main_lay)

    def on_start_clicked(self):
        self.paused = False
        self.btn_start.setVisible(False)

        self._frame_counter = 0
        self._hex_log.clear()
        self._led_dirty = False
        self._log_dirty = False
        self._archive.clear()
        self._display_mailbox = LatestFrameMailbox()
        self._export_start_time = time.perf_counter()

        self.btn_pause = MPushButton("暂停")
        self.btn_pause.setMinimumHeight(60)
        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(60)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_layout.addWidget(self.btn_pause)
        self.btn_layout.addWidget(self.btn_stop)

        log_dir = os.path.join(_get_base_dir(), "data", "capture_logs")
        csv_limit_mb = _parse_int_env("DAYU_RAW_CSV_MAX_MB", 256)
        self._diagnostics = CaptureDiagnostics(
            log_dir, max_csv_bytes=max(1, csv_limit_mb) * 1024 * 1024,
            frame_sink=self._archive.append)
        self.serial_worker = UsbWorker(
            dll_path=self.dll_path,
            vid=self.vid,
            pid=self.pid,
            timeout_ms=self.timeout_ms,
            chunk_size=self.chunk_size,
            expected_payload_bytes=96,
            # <<<8M-5>> 3m版2m首灯缺陷为旧套件特有, 8m默认不做该硬件
            # 特定校验; 现场如确认固定坏灯, 设 DAYU_REQUIRED_DARK_BITS=位索引。
            required_dark_bits=(),
            display_mailbox=self._display_mailbox,
            diagnostics=self._diagnostics,
        )
        self.serial_thread = QThread()
        self.serial_worker.moveToThread(self.serial_thread)
        self.serial_thread.started.connect(self.serial_worker.start)
        self.serial_worker.data_received.connect(self._on_hex_received)
        self.serial_thread.finished.connect(self.serial_worker.deleteLater)
        self.serial_thread.start()

    def _on_hex_received(self, hex_str: str):
        if self.paused:
            return
        self._last_hex = hex_str
        self._hex_log.append(hex_str)
        self._log_dirty = True

    def _on_led_bits_8m_received(self, *nodes):
        """8m模式 (8组96位)"""
        if self.paused:
            return
        for node in range(NODE_COUNT_8M):
            self._last_led_bits[node] = nodes[node]
        self._frame_counter += 1
        self._record_export(nodes)
        self._led_dirty = True

    def _record_export(self, nodes):
        if self._export_start_time is not None:
            ts = time.perf_counter() - self._export_start_time
            frame = b"".join(bytes(node) for node in nodes)
            self._archive.append(ts, frame)

    def _refresh_ui(self):
        # Paint the newest state at a steady rate, independent of arrival rate.
        if self.paused:
            return
        latest = self._display_mailbox.take()
        if latest is not None:
            self._frame_counter = latest.sequence
            self._last_led_bits = list(latest.nodes)
            self._led_dirty = True
        if self._log_dirty:
            self._log_dirty = False
            self.text_edit.setPlainText("\n".join(self._hex_log))
        if self._led_dirty:
            self._led_dirty = False
            for node in range(NODE_COUNT_8M):
                bits = self._last_led_bits[node]
                if bits is not None:
                    self.led_panels[node].set_leds(bits)

    def on_pause_clicked(self):
        if not self.paused:
            self.paused = True
            if self._diagnostics is not None:
                self._diagnostics.log_status("ui_paused")
            self.btn_pause.setText("继续")
        else:
            self.paused = False
            if self._diagnostics is not None:
                self._diagnostics.log_status("ui_resumed")
            self.btn_pause.setText("暂停")

    def on_stop_clicked(self):
        self.paused = True
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        if self.serial_thread:
            try:
                self.serial_thread.quit()
                self.serial_thread.wait(2000)
            except Exception:
                pass
            finally:
                self.serial_thread = None
                self.serial_worker = None
        self._save_export()
        self.text_edit.setText("")
        try:
            for panel in self.led_panels:
                panel.clear()
        except Exception:
            pass
        try:
            self.btn_pause.setVisible(False)
            self.btn_stop.setVisible(False)
            self.btn_layout.removeWidget(self.btn_pause)
            self.btn_layout.removeWidget(self.btn_stop)
            self.btn_pause.deleteLater()
            self.btn_stop.deleteLater()
        except Exception:
            pass
        self.btn_start.setVisible(True)

    def _save_export(self):
        if not self._export_frames:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "导出数据",
            f"本次采集共 {len(self._export_frames)} 帧数据，是否保存？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        save_dir = os.path.join(_get_base_dir(), "data")
        os.makedirs(save_dir, exist_ok=True)
        filename = time.strftime("led_frames_8m_%Y%m%d_%H%M%S.xlsx")
        path = os.path.join(save_dir, filename)
        try:
            wb = Workbook(write_only=True)
            ws = wb.create_sheet("LED Frames 8m")
            header = ["timestamp"]
            for segment in range(1, NODE_COUNT_8M + 1):
                header += [f"{segment}m_bit_{i}" for i in range(BITS_PER_NODE)]
            ws.append(header)
            for ts, bits in self._archive.records():
                ws.append([ts] + list(bits))
            wb.save(path)
            QtWidgets.QMessageBox.information(self, "导出成功", f"数据已保存至：\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "导出失败", f"保存文件失败：{e}")


if __name__ == '__main__':
    with application() as app:
        widget = SerialDataWidget()
        dayu_theme.apply(widget)
        widget.show()
        sys.exit(app.exec_())

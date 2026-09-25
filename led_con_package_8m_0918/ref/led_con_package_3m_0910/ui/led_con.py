
import os
import sys

# Ensure project root is importable when running `python ui/led_con.py`.
_module_dir = os.path.dirname(os.path.abspath(__file__))
if _module_dir not in sys.path:
    sys.path.insert(0, _module_dir)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from qtpy import QtWidgets
from qtpy.QtCore import QThread, QObject, Signal, Qt, QTimer
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets.qt import application
from dayu_widgets import dayu_theme
import threading
import time
from collections import deque

from openpyxl import Workbook

from hardware.receive import CyUsbInterfaceDevice, E_DATA_REPORT
from hardware.usb_worker import UsbWorker
try:
    from .led_panel import LEDPanel
except ImportError:
    from led_panel import LEDPanel
from path_utils import find_dll as _find_dll, get_base_dir as _get_base_dir


class SerialDataWidget(QtWidgets.QWidget):
    """基于 Dayu 风格的界面，用于展示 start_test 产生的数据帧（左侧文本），右侧为图表占位（不绘图）。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        # USB 设备配置（可通过环境变量覆盖）
        self.dll_path = _find_dll()
        def _parse_int_env(name, default):
            v = os.getenv(name)
            if not v:
                return default
            try:
                return int(v, 0)  # 支持十六进制如 0x04B4
            except Exception:
                return default
        self.vid = _parse_int_env("DAYU_VID", 0x04B4)
        self.pid = _parse_int_env("DAYU_PID", 0x1004)
        self.timeout_ms = _parse_int_env("DAYU_TIMEOUT", 200)
        self.chunk_size = _parse_int_env("DAYU_CHUNK", 2048)
        self.serial_thread = None
        self.serial_worker = None
        self.paused = False

        # ---- 数据导出缓存 ----
        self._export_frames = []       # list of list[int], 每帧 96 位
        self._export_timestamps = []   # list of float, 相对时间戳
        self._export_start_time = None # 采集起始时刻

        self._init_ui()
        self.setMinimumSize(1000, 600)
        # 帧计数/缓存（每10帧刷新一次UI）
        self._frame_counter = 0
        self._last_hex = ""
        self._last_led_bits = None
        # 最近5帧文本滚动缓存
        self._hex_log = deque(maxlen=10)
    
    def closeEvent(self, event):
        """窗口关闭时，确保线程正确停止"""
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        if self.serial_thread and self.serial_thread.isRunning():
            self.serial_thread.quit()
            self.serial_thread.wait(2000)
        event.accept()

    def _init_ui(self):
        self.main_lay = QtWidgets.QHBoxLayout()

        # 左侧：数据帧展示
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

        # 右侧：LED 面板
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(MDivider("LED 面板 (96)"))
        self.led_panel = LEDPanel(rows=8, cols=12, parent=self)
        right_layout.addWidget(self.led_panel, 1)

        self.main_lay.addLayout(left_layout, 1)
        self.main_lay.addLayout(right_layout, 2)
        self.setLayout(self.main_lay)

    def on_start_clicked(self):
        self.paused = False
        self.btn_start.setVisible(False)

        # 重置导出缓存
        self._export_frames.clear()
        self._export_timestamps.clear()
        self._export_start_time = time.perf_counter()

        # 创建 暂停 / 结束 按钮
        self.btn_pause = MPushButton("暂停")
        self.btn_pause.setMinimumHeight(60)
        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(60)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_layout.addWidget(self.btn_pause)
        self.btn_layout.addWidget(self.btn_stop)

        # 启用 USB 硬件 worker
        self.serial_worker = UsbWorker(
            dll_path=self.dll_path,
            vid=self.vid,
            pid=self.pid,
            timeout_ms=self.timeout_ms,
            chunk_size=self.chunk_size,
        )
        self.serial_thread = QThread()
        self.serial_worker.moveToThread(self.serial_thread)
        self.serial_thread.started.connect(self.serial_worker.start)
    # 接收数据并缓存（仅在未暂停时），每 10 帧刷新一次
        self.serial_worker.data_received.connect(self._on_hex_received)
        self.serial_worker.led_bits_signal.connect(self._on_led_bits_received)
        # 当线程结束时清理 worker
        self.serial_thread.finished.connect(self.serial_worker.deleteLater)
        self.serial_thread.start()

    def _on_hex_received(self, hex_str: str):
        if self.paused:
            return
        self._last_hex = hex_str
        # 记录到滚动日志
        try:
            self._hex_log.append(hex_str)
        except Exception:
            pass
        # 即使还没有 LED 帧，也主动刷新文本，方便看到状态/错误
        try:
            self.text_edit.setText("\n".join(self._hex_log))
        except Exception:
            pass

    def _on_led_bits_received(self, bits: list):
        if self.paused:
            return
        self._last_led_bits = bits
        self._frame_counter += 1

        # 记录到导出缓存
        if self._export_start_time is not None:
            ts = time.perf_counter() - self._export_start_time
            self._export_frames.append(list(bits))
            self._export_timestamps.append(ts)

        # 方案A：首帧立刷，其后每10帧刷新一次
        if self._frame_counter == 1 or (self._frame_counter % 10 == 0):
            # 刷新文本为最近5帧（滚动显示）
            try:
                self.text_edit.setText("\n".join(self._hex_log))
            except Exception:
                pass
            # 刷新LED面板
            if self._last_led_bits is not None:
                self.led_panel.set_leds(self._last_led_bits)

    def on_pause_clicked(self):
        if not self.paused:
            self.paused = True
            self.btn_pause.setText("继续")
        else:
            self.paused = False
            self.btn_pause.setText("暂停")

    def on_stop_clicked(self):
        self.paused = True
        # 停止 worker（先设置停止事件）
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        
        # 等待线程完全结束后再清理
        if self.serial_thread:
            try:
                self.serial_thread.quit()
                self.serial_thread.wait(2000)  # 等待最多2秒
            except Exception:
                pass
            finally:
                # 清理线程引用
                self.serial_thread = None
                self.serial_worker = None

        # 导出数据
        self._save_export()

        # 清空文本
        self.text_edit.setText("")
        # 清空 LED 面板
        try:
            self.led_panel.clear()
        except Exception:
            pass

        # 移除暂停和结束按钮
        try:
            self.btn_pause.setVisible(False)
            self.btn_stop.setVisible(False)
            self.btn_layout.removeWidget(self.btn_pause)
            self.btn_layout.removeWidget(self.btn_stop)
            self.btn_pause.deleteLater()
            self.btn_stop.deleteLater()
        except Exception:
            pass

        # 恢复开始按钮
        self.btn_start.setVisible(True)

    def _save_export(self):
        """将缓存的 LED 位图帧导出为 Excel 文件。"""
        if not self._export_frames:
            return

        # 弹出确认对话框
        reply = QtWidgets.QMessageBox.question(
            self,
            "导出数据",
            f"本次采集共 {len(self._export_frames)} 帧数据，是否保存？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        # 固定保存路径
        save_dir = os.path.join(_get_base_dir(), "data")
        os.makedirs(save_dir, exist_ok=True)
        filename = time.strftime("led_frames_%Y%m%d_%H%M%S.xlsx")
        path = os.path.join(save_dir, filename)

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "LED Frames"
            # 表头：timestamp, bit_0, bit_1, ..., bit_95
            header = ["timestamp"] + [f"bit_{i}" for i in range(96)]
            ws.append(header)
            # 逐行写入
            for ts, bits in zip(self._export_timestamps, self._export_frames):
                ws.append([ts] + bits)
            wb.save(path)
            QtWidgets.QMessageBox.information(
                self, "导出成功", f"数据已保存至：\n{path}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "导出失败", f"保存文件失败：{e}")


if __name__ == '__main__':
    with application() as app:
        widget = SerialDataWidget()
        dayu_theme.apply(widget)
        widget.show()
        sys.exit(app.exec_())

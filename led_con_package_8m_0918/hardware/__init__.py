"""
hardware — L1 硬件采集层 (8m版)

包含 USB 协议解析、DLL ctypes 封装、Qt 数据采集 Worker。
<<<8M-1>> 8m包仅提供 usb_worker_8m (1m/3m版worker见 ref 目录)。
"""
from .protocol import protocol_parser, ProtocolParser, E_DATA_REPORT, E_ACK, E_STATUS_REPORT
from .receive import CyUsbInterfaceDevice, CyUsbInterfaceDLL

try:
    from .usb_worker_8m import UsbWorker as UsbWorker8M
except Exception:
    UsbWorker8M = None

__all__ = [
    "protocol_parser", "ProtocolParser",
    "E_DATA_REPORT", "E_ACK", "E_STATUS_REPORT",
    "CyUsbInterfaceDevice", "CyUsbInterfaceDLL",
    "UsbWorker8M",
]

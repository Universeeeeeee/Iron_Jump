"""
hardware — L1 硬件采集层

包含 USB 协议解析、DLL ctypes 封装、Qt 数据采集 Worker。
"""
from .protocol import protocol_parser, ProtocolParser, E_DATA_REPORT, E_ACK, E_STATUS_REPORT
from .receive import CyUsbInterfaceDevice, CyUsbInterfaceDLL
from .usb_worker import UsbWorker
from .sensor_frame import DeviceLayout, SensorSegment, SensorFrame, AcquisitionIssue

__all__ = [
    "protocol_parser", "ProtocolParser",
    "E_DATA_REPORT", "E_ACK", "E_STATUS_REPORT",
    "CyUsbInterfaceDevice", "CyUsbInterfaceDLL",
    "UsbWorker", "DeviceLayout", "SensorSegment", "SensorFrame", "AcquisitionIssue",
]

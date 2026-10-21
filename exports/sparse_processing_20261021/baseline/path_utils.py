"""
path_utils.py — 路径工具函数

提供打包环境与开发环境的路径自动适配，供 data_show.py / led_con.py 等共用。
"""
import os
import sys

# 开发环境中 DLL 的默认位置（hardware/ 子目录）
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_DEV_DLL_PATH = os.path.join(_PROJECT_ROOT, "hardware", "CyUsbInterface.dll")


def get_base_dir():
    """获取程序基础目录 (兼容开发环境和 PyInstaller 打包环境)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_dll():
    """按优先级查找 DLL: 环境变量 → hardware/ → 程序根目录 → _MEIPASS → 开发路径"""
    env = os.getenv("DAYU_DLL")
    if env and os.path.isfile(env):
        return env
    # 优先在 hardware/ 子目录中查找
    hw = os.path.join(get_base_dir(), "hardware", "CyUsbInterface.dll")
    if os.path.isfile(hw):
        return hw
    # 兼容旧版：根目录
    base = os.path.join(get_base_dir(), "CyUsbInterface.dll")
    if os.path.isfile(base):
        return base
    if hasattr(sys, '_MEIPASS'):
        mei = os.path.join(sys._MEIPASS, "CyUsbInterface.dll")
        if os.path.isfile(mei):
            return mei
    if os.path.isfile(_DEV_DLL_PATH):
        return _DEV_DLL_PATH
    return hw  # 返回预期路径，让错误信息有意义

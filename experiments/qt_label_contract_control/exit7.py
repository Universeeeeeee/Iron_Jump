"""Lower-level exit-status control; no Qt or application imports."""
import ctypes as C
import sys

assert sys.platform == 'win32'
exit_process = C.WinDLL('kernel32').ExitProcess
exit_process.argtypes = [C.c_uint32]
exit_process.restype = None
exit_process(7)
raise AssertionError('ExitProcess unexpectedly returned')

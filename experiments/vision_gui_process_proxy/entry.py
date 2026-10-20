"""Guarded saved-input GUI entry; native camera hardware is never opened."""
import runpy
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];SESSION=ROOT/'experiments/session_gui_vision'

def main():
    for folder in (ROOT,ROOT/'experiments/gil_gui_calibration',ROOT/'experiments/gil_workload_finalization',SESSION,HERE):sys.path.insert(0,str(folder))
    from gate import require
    require(HERE)
    from camera.control_service import CameraControlService
    import links
    original=CameraControlService.__init__
    def control_init(control,*args,**kwargs):
        if kwargs.get('command') is not None:raise ValueError('Unexpected SDK override')
        kwargs['command']=[sys.executable,'-u',str(SESSION/'fake_sdk.py'),str(HERE/'runs01/sdk_backend.json')]
        original(control,*args,**kwargs);links.attach(control)
    CameraControlService.__init__=control_init;links.sdk_patch_installed=True
    try:runpy.run_path(str(HERE/'gui.py'),run_name='__main__')
    finally:CameraControlService.__init__=original

if __name__=='__main__':main()

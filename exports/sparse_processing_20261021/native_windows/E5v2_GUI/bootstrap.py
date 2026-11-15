"""Install admitted calculation candidates; fence every physical acquisition path."""
import os
from pathlib import Path
import sys

CALLBACK_ERRORS=[]
HARDWARE_ATTEMPTS=[]


def forbidden(name):
    def reject(*args,**kwargs):
        HARDWARE_ATTEMPTS.append(name)
        raise RuntimeError('Offline experiment forbids '+name)
    return reject


def fences():
    from hardware.usb_worker import UsbWorker
    from hardware.receive import CyUsbInterfaceDevice, CyUsbInterfaceDLL
    from camera.control_service import CameraControlService
    UsbWorker.__init__=forbidden('UsbWorker constructor')
    CyUsbInterfaceDevice.__init__=forbidden('USB device constructor')
    CyUsbInterfaceDLL.__init__=forbidden('USB DLL constructor')
    CameraControlService.__init__=forbidden('Camera SDK process constructor')


def install():
    fences()
    sys.excepthook=lambda kind,value,tb:CALLBACK_ERRORS.append(repr(value))
    variant=os.environ.get('IRON_OFFLINE_VARIANT','baseline')
    if variant=='baseline':return
    assert variant=='combined'
    lab=Path(os.environ['IRON_SPARSE_LAB'])
    sys.path.insert(0,str(lab))
    from candidates import CancelledRuntime,processor_class,enabled
    import hardware.walking_preflight as preflight
    import engine.device_quality_session as quality
    import engine.modes.walking_processor as walking
    import engine.modes.overground_running_processor as running
    if enabled('combined','runtime'):
        preflight.RuntimeBeamEvidence=quality.RuntimeBeamEvidence=CancelledRuntime
    walking.WalkingProcessor=processor_class(walking.WalkingProcessor,'combined')
    running.OvergroundRunningProcessor=processor_class(running.OvergroundRunningProcessor,'combined')
    import engine.walking_session as session
    session.WalkingProcessor=walking.WalkingProcessor

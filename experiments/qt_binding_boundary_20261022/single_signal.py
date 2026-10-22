"""Remove only the diagnostic Qt relay; retain the production-shaped Qt emit.

The original wire control emitted UsbWorker -> validator -> ReplayWorker ->
inbox using two Qt signals. Production has one. Replace the first (diagnostic)
hop with a Python call; all frame validation and the real inbox signal remain.
"""


class ValidationRelay:
    def __init__(self, callback):
        self.callback = callback

    def emit(self, frame):
        self.callback(frame)


def install(r):
    original = r.ReplayWorker.__init__

    def init(self, **kwargs):
        original(self, **kwargs)
        self.wire_worker.sensor_frame_received.disconnect(self.deliver_wire)
        self.wire_worker.sensor_frame_received = ValidationRelay(self.deliver_wire)
        assert isinstance(self.wire_worker.sensor_frame_received, ValidationRelay)
        assert not isinstance(self.sensor_frame_received, ValidationRelay)

    r.ReplayWorker.__init__ = init

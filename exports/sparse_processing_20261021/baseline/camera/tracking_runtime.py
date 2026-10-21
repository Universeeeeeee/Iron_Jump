"""Speed loop run by the existing settings process's sole SDK owner."""
import time
import threading
from dataclasses import asdict

from camera.pose_tracking import PoseTrackingMailbox


class TrackingRuntime:
    def __init__(self, sdk, log, *, clock=time.perf_counter):
        self.sdk = sdk
        self.log = log
        self.clock = clock
        self.active = False
        self.generation = -1
        self.mailbox = PoseTrackingMailbox()
        self._resume_after = float('-inf')
        self._barrier_sequence = -1
        self._state_lock = threading.RLock()

    def _call(self, method, *args):
        start = self.clock()
        try:
            result = getattr(self.sdk, method)(*args)
        except Exception as exc:
            self.log({'event': 'sdk_call', 'method': method, 'args': args,
                      'started_at': start, 'returned_at': self.clock(), 'error': str(exc)})
            raise
        self.log({'event': 'sdk_call', 'method': method, 'args': args,
                  'started_at': start, 'returned_at': self.clock(), 'result': result})
        return result

    def start(self, generation):
        with self._state_lock:
            if type(generation) is not int or generation <= self.generation:
                raise ValueError('Tracking generation must increase')
            self.active = False
            self.generation = generation
            self.mailbox = PoseTrackingMailbox()
            self._barrier_sequence = -1
        self._call('set_speed', 0, 0)
        self._call('disable_ai')
        with self._state_lock:
            self.active = True

    def submit(self, generation, update):
        with self._state_lock:
            if self.active and generation == self.generation:
                record = update.inference
                source = record.frame_metadata if record else None
                if update.status == 'pose' and source is not None:
                    if min(source.callback_time_s, record.frame_timestamp_s) < self._resume_after:
                        return
                self.mailbox.submit(update)

    def submit_packet(self, packet):
        from camera.pose_transport import decode_update
        generation = packet['generation']
        self.log({'event': 'pose_input', 'received_at': self.clock(), 'packet': packet})
        with self._state_lock:
            if not self.active or generation != self.generation:
                return
            sequence = packet['barrier_sequence']
            if sequence < self._barrier_sequence:
                return
            if sequence > self._barrier_sequence:
                self._barrier_sequence = sequence
                if packet['barrier'] is not None:
                    self.submit(generation, decode_update(packet['barrier']))
            self.submit(generation, decode_update(packet['update']))

    def _current(self, mailbox, generation, command):
        with self._state_lock:
            return (self.active and generation == self.generation and mailbox is self.mailbox
                    and mailbox.is_current(command)
                    and (not (command.pitch or command.pan)
                         or 0 <= self.clock()-command.captured_at <= mailbox.timeout))

    def tick(self):
        with self._state_lock:
            if not self.active:
                return
            mailbox, generation = self.mailbox, self.generation
        command = mailbox.command(self.clock())
        self.log({'event': 'tracking_decision', 'generation': generation,
                  'pitch': command.pitch, 'pan': command.pan,
                  'captured_at': command.captured_at, 'reason': command.reason,
                  'framing': asdict(command.framing) if command.framing else None})
        try:
            if self._current(mailbox, generation, command):
                self._call('set_speed', command.pitch, command.pan)
            else:
                self._call('set_speed', 0, 0)
            # If invalidated during a native call, stop as soon as it returns.
            if not self._current(mailbox, generation, command):
                self._call('set_speed', 0, 0)
        except Exception:
            with self._state_lock:
                self.active = False
            # A rejected or blocked command is not evidence of a physical stop.
            self._call('set_speed', 0, 0)
            raise

    def stop(self):
        with self._state_lock:
            self.active = False
            self.mailbox = PoseTrackingMailbox()
        self._call('set_speed', 0, 0)

    def setting(self, method, function, *args):
        with self._state_lock:
            if self.active and method in {'set_ai_mode', 'set_ai_off', 'set_fov'}:
                raise RuntimeError('Stop SDK tracking before changing AI or FOV')
            active = self.active
            if active:
                self.mailbox = PoseTrackingMailbox()
        # Stop before a potentially slow setting; only a new pose can resume.
        if active:
            self._call('set_speed', 0, 0)
        try:
            result = function(*args)
            if result != 0:
                raise RuntimeError(f'SDK setting failed: {method} ({result})')
            return result
        except Exception:
            with self._state_lock:
                self.active = False
            raise
        finally:
            with self._state_lock:
                if self.active:
                    self._resume_after = self.clock()
                    self.mailbox = PoseTrackingMailbox()

"""GUI-independent reaction trials using host receive/request time estimates.

Device samples establish continuity and confirm state edges. They are never
subtracted from host timestamps, and software requests are not physical onsets.
"""
from dataclasses import dataclass
from random import Random
from time import perf_counter_ns

from config.reaction_config import ReactionConfig, validate_reaction_config
from config.reaction_report import ReactionTestReport, ReactionTrialRecord
from hardware.sensor_frame import SensorFrame


@dataclass(frozen=True)
class ReactionEvent:
    kind: str
    state: str
    trial_index: int
    modality: str | None
    host_ns: int
    record: ReactionTrialRecord | None = None


class ReactionSession:
    STALE_NS = 500_000_000
    STIMULUS_ACK_TIMEOUT_NS = 1_000_000_000
    ACTIVE_STATES = {"preparing", "waiting", "stimulus_pending", "responding"}

    def __init__(self, config: ReactionConfig, *, clock=perf_counter_ns, rng=None):
        errors = validate_reaction_config(config)
        if errors:
            raise ValueError(" ".join(errors))
        self.config = config
        self._clock = clock
        self._rng = rng if rng is not None else Random()
        self.state = "idle"
        self.trials = []
        self._events = []
        self._trial_index = 0
        self._modality = None
        self._request_ns = None
        self._pending_ns = None
        self._deadline_ns = None
        self._rest_until_ns = None
        self._start_ns = None
        self._finish_reason = "manual"
        self._last_frame = None
        self._previous_frame = None
        self._ready_start = None
        self._candidate = None
        self._confirmed_response = None
        self._confirmation_frame = None
        self._stimulus_due_ns = None

    @property
    def is_finished(self):
        return self.state == "finished"

    def _now(self, host_ns):
        return self._clock() if host_ns is None else host_ns

    def _emit(self, kind, now, record=None):
        self._events.append(ReactionEvent(kind, self.state, self._trial_index,
                                          self._modality, now, record))

    def _set_state(self, state, now):
        self.state = state
        self._emit("state_changed", now)

    def _reset_observation(self):
        self._last_frame = None
        self._ready_start = None
        self._candidate = None
        self._confirmed_response = None
        self._confirmation_frame = None

    def _start_trial(self, now):
        self._trial_index = len(self.trials) + 1
        modes = {"Visual stimulus": "visual", "Acoustic stimulus": "acoustic"}
        self._modality = modes.get(self.config.stimulus_type)
        if self._modality is None:
            self._modality = self._rng.choice(("visual", "acoustic"))
        self._start_ns = now
        self._request_ns = self._pending_ns = self._deadline_ns = None
        self._stimulus_due_ns = None
        self._reset_observation()
        self._set_state("preparing", now)

    def begin(self, host_ns=None):
        self._events = []
        if self.state != "idle":
            return ()
        self._start_trial(self._now(host_ns))
        return tuple(self._events)

    def snapshot(self):
        return {
            "state": self.state,
            "trial_index": self._trial_index,
            "total_trials": self.config.number_of_repetitions,
            "stimulus_type": self.config.stimulus_type,
            "next_allowed": self.state == "manual_wait",
            "latest_trial": self.trials[-1] if self.trials else None,
            "timing_quality": "uncalibrated",
        }

    def _finish_trial(self, status, now, *, response=None, flags=(), halt=False):
        request = self._request_ns
        rt = None
        if status == "valid" and response is not None and request is not None:
            rt = (response.received_monotonic_ns - request) / 1_000_000
        record = ReactionTrialRecord(
            index=self._trial_index, modality=self._modality,
            action="takeoff" if self.config.start_position == "Inside area" else "entry",
            status=status, stimulus_request_host_ns=request,
            response_received_host_ns=response.received_monotonic_ns if response else None,
            response_sample_index=response.sample_index if response else None,
            response_frame_index=response.frame_index if response else None,
            reaction_time_ms=rt, quality_flags=tuple(flags),
            stimulus_scheduled_host_ns=self._pending_ns,
            confirmation_sample_index=self._confirmation_frame.sample_index if self._confirmation_frame else None,
            confirmation_received_host_ns=self._confirmation_frame.received_monotonic_ns if self._confirmation_frame else None,
            stream_id=response.stream_id if response else (self._last_frame.stream_id if self._last_frame else None),
        )
        self.trials.append(record)
        self._reset_observation()
        self._request_ns = self._pending_ns = self._deadline_ns = None
        self._stimulus_due_ns = None
        self._emit("trial_finished", now, record)
        if halt or len(self.trials) >= self.config.number_of_repetitions:
            self._finish_reason = "error" if halt else "completed"
            self._set_state("finished", now)
            self._emit("finished", now)
        else:
            self._rest_until_ns = now + self.config.minimum_pause_ms * 1_000_000
            self._set_state("rest", now)

    def _issue(self, code, now):
        if self.state in self.ACTIVE_STATES:
            self._finish_trial("gap", now, flags=(code,), halt=True)
        elif self.state in {"rest", "manual_wait"}:
            self._finish_reason = "error"
            self._reset_observation()
            self._set_state("finished", now)
            self._emit("finished", now)

    def on_issue(self, code, host_ns=None):
        self._events = []
        self._issue(code, self._now(host_ns))
        return tuple(self._events)

    def _frame_error(self, frame):
        bit_count = frame.layout.bit_count
        if len(frame.contact_bits) != bit_count or len(frame.valid_bits) != bit_count:
            return "unsupported_layout"
        if frame.valid_bits != b"\x01" * bit_count or frame.layout.invalid_bit_indices:
            return "invalid_beams"
        if any(bit not in (0, 1) for bit in frame.contact_bits):
            return "invalid_contact_bits"
        if all(frame.contact_bits):
            return "all_beams_blocked"
        if frame.dropped_frames_before or "frame_gap" in frame.quality_flags:
            return "frame_gap"
        if frame.quality_flags:
            return "sensor_quality:" + ",".join(frame.quality_flags)
        previous = self._previous_frame
        if previous is not None:
            if frame.stream_id != previous.stream_id or frame.layout != previous.layout:
                return "stream_changed"
            if frame.sample_index != previous.sample_index + 1:
                return "frame_gap"
            if frame.received_monotonic_ns < previous.received_monotonic_ns:
                return "host_clock_regression"
            if frame.received_monotonic_ns - previous.received_monotonic_ns >= self.STALE_NS:
                return "stale_sensor_data"
        return None

    def on_frame(self, frame: SensorFrame):
        self._events = []
        if self.state not in self.ACTIVE_STATES | {"rest", "manual_wait"}:
            return ()
        now = frame.received_monotonic_ns
        error = self._frame_error(frame)
        if error:
            self._issue(error, now)
            return tuple(self._events)
        self._previous_frame = frame
        if self.state in {"rest", "manual_wait"}:
            return ()
        self._last_frame = frame
        baseline = self.config.start_position == "Inside area"
        occupied = any(frame.contact_bits)
        if self.state == "preparing":
            if occupied != baseline:
                self._ready_start = None
            else:
                if self._ready_start is None:
                    self._ready_start = frame.sample_index
                if frame.sample_index - self._ready_start >= self.config.ready_hold_ms:
                    delay = self._rng.randint(self.config.stimulus_delay_min_ms,
                                              self.config.stimulus_delay_max_ms)
                    self._stimulus_due_ns = now + delay * 1_000_000
                    self._set_state("waiting", now)
        elif self._confirmed_response is not None:
            pass
        elif occupied == baseline:
            self._candidate = None
        else:
            if self._candidate is None:
                self._candidate = frame
            if frame.sample_index - self._candidate.sample_index >= self.config.confirmation_ms:
                response = self._candidate
                self._confirmed_response = response
                self._confirmation_frame = frame
                if self.state == "stimulus_pending":
                    pass
                elif self._request_ns is None or response.received_monotonic_ns < self._request_ns:
                    self._finish_trial("early", now, response=response, flags=("movement_before_stimulus_request",))
                elif response.received_monotonic_ns > self._deadline_ns:
                    self._finish_trial("timeout", now, response=response, flags=("response_after_deadline",))
                elif self.state == "responding":
                    self._finish_trial("valid", now, response=response)
                # A confirmed pending edge is retained until acknowledgement.
        self._expire(now)
        return tuple(self._events)

    def _expire(self, now):
        if self.state in self.ACTIVE_STATES:
            last_ns = self._last_frame.received_monotonic_ns if self._last_frame else self._start_ns
            if now - last_ns >= self.STALE_NS:
                self._issue("stale_sensor_data", now)
                return
        if self.state == "stimulus_pending" and now - self._pending_ns >= self.STIMULUS_ACK_TIMEOUT_NS:
            self._finish_trial("stimulus_failed", now, flags=("stimulus_ack_timeout",), halt=True)
        elif self.state == "responding" and now > self._deadline_ns:
            if self._candidate is None or self._candidate.received_monotonic_ns > self._deadline_ns:
                self._finish_trial("timeout", now, flags=("response_timeout",))

    def poll(self, host_ns=None):
        self._events = []
        now = self._now(host_ns)
        self._expire(now)
        if self.state == "waiting" and now >= self._stimulus_due_ns:
            self._pending_ns = now
            self._set_state("stimulus_pending", now)
            self._emit("stimulus_requested", now)
        elif self.state == "rest" and now >= self._rest_until_ns:
            if self.config.sequence_type == "Manual":
                self._set_state("manual_wait", now)
            else:
                self._start_trial(now)
        return tuple(self._events)

    def acknowledge_stimulus(self, trial_index, request_host_ns, modality=None, success=True, *, host_ns=None):
        self._events = []
        if self.state != "stimulus_pending" or trial_index != self._trial_index:
            return ()
        now = self._now(host_ns)
        self._expire(now)
        if self.state != "stimulus_pending":
            return tuple(self._events)
        if not success or (modality is not None and modality != self._modality):
            self._finish_trial("stimulus_failed", now, flags=("stimulus_request_failed",), halt=True)
            return tuple(self._events)
        if type(request_host_ns) is not int or not self._pending_ns <= request_host_ns <= now:
            self._finish_trial("stimulus_failed", now, flags=("invalid_stimulus_request_time",), halt=True)
            return tuple(self._events)
        self._request_ns = request_host_ns
        self._deadline_ns = request_host_ns + self.config.response_timeout_ms * 1_000_000
        self._set_state("responding", request_host_ns)
        if self._confirmed_response is not None:
            response = self._confirmed_response
            status = "early" if response.received_monotonic_ns < request_host_ns else "valid"
            if response.received_monotonic_ns > self._deadline_ns:
                status = "timeout"
            flags = ("movement_before_stimulus_request",) if status == "early" else ()
            self._finish_trial(status, now, response=response, flags=flags)
        return tuple(self._events)

    def next_trial(self, host_ns=None):
        self._events = []
        now = self._now(host_ns)
        if self.config.sequence_type == "Manual" and (
            self.state == "manual_wait" or (self.state == "rest" and now >= self._rest_until_ns)
        ):
            self._start_trial(now)
        return tuple(self._events)

    def cancel(self, host_ns=None):
        return self.halt("cancelled", host_ns)

    def halt(self, reason="manual", host_ns=None):
        self._events = []
        now = self._now(host_ns)
        if self.state in {"idle", "finished"}:
            return ()
        if self.state in self.ACTIVE_STATES:
            self._finish_trial("cancelled", now, flags=(reason,), halt=True)
        else:
            self._reset_observation()
            self._set_state("finished", now)
            self._emit("finished", now)
        self._finish_reason = reason
        return tuple(self._events)

    def build_report(self, reason=None):
        snapshot = self.config.to_dict()
        snapshot.update(
            hardware_sample_rate_hz=1000,
            host_clock="perf_counter_ns",
            timing_method="host_receive_minus_stimulus_request",
            timing_quality="uncalibrated",
            actual_stimulus_onset_available=False,
            device_host_synchronization="unavailable",
        )
        return ReactionTestReport(tuple(self.trials), self._finish_reason if reason is None else reason,
                                  snapshot)

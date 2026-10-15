"""Experimental single-sample fusion. No Qt objects or window lifecycle in JIT."""
import numpy as np
from numba import njit
from hardware.walking_preflight import RuntimeBeamEvidence


def update(bits, previous, old_bits, old_changes, counts, transitions,
           previous_mask, full, threshold):
    changes = np.empty(len(bits), dtype=np.uint8)
    mask = np.empty(len(bits) if full else 0, dtype=np.bool_)
    changed_mask = full and len(previous_mask) == 0
    for i in range(len(bits)):
        delta = bits[i] ^ previous[i] if len(previous) else 0
        changes[i] = delta
        counts[i] += bits[i]
        transitions[i] += delta
        if len(old_bits):
            counts[i] -= old_bits[i]
            transitions[i] -= old_changes[i]
        if full:
            flagged = counts[i] >= threshold or transitions[i] >= 20
            mask[i] = flagged
            if len(previous_mask) and flagged != previous_mask[i]:
                changed_mask = True
    return changes, mask, changed_mask


# Compile independently: disable disk cache so the two dispatchers cannot reuse
# a cached wrapper built with the other GIL setting.
KERNELS = {'B': njit(nogil=False, cache=False)(update),
           'C': njit(nogil=True, cache=False)(update)}


def runtime_class(variant):
    kernel = KERNELS[variant]

    class FusedRuntime(RuntimeBeamEvidence):
        def _reset(self):
            super()._reset()
            self._empty = np.empty(0, dtype=np.uint8)
            self.suspicious_mask = np.empty(0, dtype=np.bool_)
            self.mask_changed = False

        def observe(self, frame):
            previous = self.last_frame
            self.last_frame = frame
            if previous and (frame.stream_id != previous.stream_id or frame.layout != previous.layout
                             or frame.sample_index != previous.sample_index + 1):
                self._reset()
            if (len(frame.contact_bits) != frame.layout.bit_count
                    or len(frame.valid_bits) != frame.layout.bit_count or b'\x00' in frame.valid_bits
                    or frame.dropped_frames_before
                    or any(flag != 'all_beams_blocked' for flag in frame.quality_flags)):
                self._reset()
                return False
            bits = np.frombuffer(frame.contact_bits, dtype=np.uint8)
            if self._previous is None:
                self._counts = np.zeros(len(bits), dtype=np.int32)
                self._transitions = np.zeros(len(bits), dtype=np.int32)
            old_bits, old_changes = (self._window.popleft() if len(self._window) == self.policy.samples
                                     else (self._empty, self._empty))
            full = len(self._window) + 1 >= self.policy.samples
            changes, mask, changed = kernel(
                bits, self._previous if self._previous is not None else self._empty,
                old_bits, old_changes, self._counts, self._transitions,
                self.suspicious_mask, full, self.policy.samples * .95)
            self._window.append((bits, changes))
            self._previous = bits
            self.healthy_samples = len(self._window)
            self.suspicious_mask, self.mask_changed = mask, changed
            return True

    return FusedRuntime


def warmup():
    """Use disposable state; verify the generated wrappers really differ in GIL handling."""
    from hardware.beam_quality import BeamQualityPolicy
    from hardware.sensor_frame import DeviceLayout, SensorFrame
    layout = DeviceLayout.linear(1)
    result = {}
    for variant in KERNELS:
        evidence = runtime_class(variant)(BeamQualityPolicy(observation_seconds=1))
        # Exercise read-only previous/expired views as well as writable delta arrays.
        for i in range(1002):
            evidence.observe(SensorFrame('warmup', layout, i, i, i * 1000000,
                                        bytes(96), b'\1' * 96, b'\xff' * 12))
        kernel = KERNELS[variant]
        llvm = '\n'.join(kernel.inspect_llvm().values())
        releases_gil = 'PyEval_SaveThread' in llvm and 'PyEval_RestoreThread' in llvm
        assert releases_gil == (variant == 'C'), (variant, 'unexpected generated wrapper')
        assert kernel.nopython_signatures
        result[variant] = {'nopython_signatures': [str(s) for s in kernel.nopython_signatures],
                           'targetoptions': kernel.targetoptions,
                           'generated_wrapper_releases_gil': releases_gil}
    return result

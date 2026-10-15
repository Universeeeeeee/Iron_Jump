"""Install an experimental runtime and its adjacent quality mask calculation in memory."""
import inspect
from pathlib import Path
import engine.device_quality_session as quality
from fused_runtime import runtime_class

HERE = Path(__file__).resolve().parent
ORIGINAL_RUNTIME = quality.RuntimeBeamEvidence
ORIGINAL_ON_FRAME = quality.DeviceQualitySession.on_frame


def install(variant):
    if variant == 'A':
        quality.RuntimeBeamEvidence = ORIGINAL_RUNTIME
        quality.DeviceQualitySession.on_frame = ORIGINAL_ON_FRAME
        return
    quality.RuntimeBeamEvidence = runtime_class(variant)
    source = inspect.getsource(ORIGINAL_ON_FRAME)
    import textwrap
    source = textwrap.dedent(source)
    source = source.replace('@Slot(object)\n', '', 1)
    original = '''        persistent_threshold = samples * .95
        flagged = ((self._runtime._counts >= persistent_threshold)
                   | (self._runtime._transitions >= 20))
        if not np.array_equal(flagged, self._runtime_suspicious_mask):'''
    replacement = '''        flagged = self._runtime.suspicious_mask
        if self._runtime.mask_changed:'''
    assert source.count(original) == 1, 'Frozen quality block changed'
    source = source.replace(original, replacement)
    # Keep the surrounding audited quality method byte-for-byte, changing only
    # the adjacent mask calculation. Persist the actual compiled source for audit.
    path = HERE / 'generated' / 'quality_fused_on_frame.py'
    path.parent.mkdir(exist_ok=True)
    path.write_text(source, encoding='utf-8')
    namespace = dict(quality.__dict__)
    exec(compile(source, str(path), 'exec'), namespace)
    quality.DeviceQualitySession.on_frame = namespace['on_frame']

"""Operator-registered unavailable physical beams; never renumber coordinates."""
from qtpy.QtCore import QSettings


def load_known_beams(settings=None):
    settings = settings or QSettings("IronJump", "DeviceQuality")
    value = settings.value("known_bad_beams", [])
    return (value,) if isinstance(value, str) else tuple(value or ())


def known_bad_indices(layout, addresses):
    if layout is None:
        return ()
    indices = set()
    for address in addresses:
        segment_id, separator, led = str(address).partition(":")
        if not separator or not led.isdigit() or not 1 <= int(led) <= 96:
            continue
        for index, segment in enumerate(layout.segments):
            if segment.segment_id == segment_id:
                indices.add(index * 96 + int(led) - 1)
    return tuple(sorted(indices))

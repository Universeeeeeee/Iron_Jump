"""Small line icons rendered by Qt, independent of platform symbol fonts."""

from functools import lru_cache

from qtpy.QtCore import QByteArray
from qtpy.QtGui import QIcon, QPixmap

from ui.theme import PALETTE


_PATHS = {
    "athletes": '<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M21 21v-3a6 6 0 0 0-3-5"/>',
    "test": '<path d="m8 4 12 8-12 8Z"/>',
    "results": '<path d="M4 20V10h4v10m4 0V4h4v16m4 0V8h2v12M2 20h21"/>',
    "settings": '<path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    "camera": '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="m8 6 2-3h4l2 3"/><circle cx="12" cy="13" r="4"/>',
    "export": '<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
    "pause": '<path d="M8 4v16M16 4v16"/>',
}


@lru_cache(maxsize=16)
def icon(name: str, active: bool = False) -> QIcon:
    color = PALETTE["accent"] if active else PALETTE["text_secondary"]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" '
        f'stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>'
    )
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(svg.encode()), "SVG")
    return QIcon(pixmap)


def navigation_pixmap(name: str, active: bool = False) -> QPixmap:
    pixmap = icon(name, active).pixmap(40, 40)
    pixmap.setDevicePixelRatio(2)
    return pixmap

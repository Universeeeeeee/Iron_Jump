"""QLabel video surface with frame-local, original-pixel annotations."""

import math

from qtpy.QtCore import QPointF, QRectF, Qt, Signal
from qtpy.QtGui import QColor, QPainter, QPen
from qtpy.QtWidgets import QLabel

from camera.video_annotations import angle_degrees


class AnnotationCanvas(QLabel):
    angle_created = Signal(object)
    angle_edited = Signal(str, object)
    selection_changed = Signal(str)
    message = Signal(str)

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.records = []
        self.index = -1
        self.image_size = (0, 0)
        self.times = None
        self.estimated = False
        self.annotations_visible = False
        self.editable = False
        self.tool = "select"
        self.selected_id = ""
        self.draft = []
        self._drag = None
        self.setMouseTracking(True)

    def reset_annotations(self):
        self.records = []
        self.index = -1
        self.times = None
        self.annotations_visible = False
        self.editable = False
        self.tool = "select"
        self.select("")
        self.cancel_draft()

    def set_frame(self, index, width, height):
        if index != self.index:
            self.cancel_draft()
            selected = next((r for r in self.records if r["id"] == self.selected_id), None)
            if selected is not None and selected["kind"] == "angle" and selected["frame"] != index:
                self.select("")
        self.index = index
        self.image_size = (width, height)
        self.annotations_visible = True
        self.update()

    def set_editable(self, enabled):
        self.editable = enabled
        if not enabled:
            self.cancel_draft()

    def set_tool(self, tool):
        self.tool = tool
        self.cancel_draft()
        self.setCursor(Qt.CrossCursor if tool == "angle" else Qt.ArrowCursor)

    def cancel_draft(self):
        self.draft = []
        self._drag = None
        self.update()

    def select(self, record_id):
        self.selected_id = record_id
        self.selection_changed.emit(record_id)
        self.update()

    def image_rect(self):
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return QRectF()
        width = pixmap.width() / pixmap.devicePixelRatioF()
        height = pixmap.height() / pixmap.devicePixelRatioF()
        rect = self.contentsRect()
        return QRectF(rect.x() + (rect.width() - width) / 2,
                      rect.y() + (rect.height() - height) / 2, width, height)

    def to_screen(self, point):
        rect = self.image_rect()
        width, height = self.image_size
        return QPointF(rect.x() + point[0] * rect.width() / width,
                       rect.y() + point[1] * rect.height() / height)

    def to_image(self, point, clamp=False):
        rect = self.image_rect()
        width, height = self.image_size
        if rect.isEmpty() or width <= 0 or height <= 0 or (not clamp and not rect.contains(point)):
            return None
        return [max(0, min(width - 1, (point.x() - rect.x()) * width / rect.width())),
                max(0, min(height - 1, (point.y() - rect.y()) * height / rect.height()))]

    def visible_angles(self):
        return [r for r in self.records if r["kind"] == "angle" and r["frame"] == self.index]

    def visible_intervals(self):
        return [r for r in self.records if r["kind"] == "interval" and r["start"] <= self.index <= r["end"]]

    @staticmethod
    def _distance(point, start, end):
        dx, dy = end.x() - start.x(), end.y() - start.y()
        norm = dx * dx + dy * dy
        t = max(0, min(1, ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / norm)) if norm else 0
        return math.hypot(point.x() - start.x() - t * dx, point.y() - start.y() - t * dy)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.editable:
            return super().mousePressEvent(event)
        self.setFocus()
        position = QPointF(event.pos())
        point = self.to_image(position)
        if point is None:
            if self.tool == "select":
                self.select("")
            return
        if self.tool == "angle":
            self.select("")
            points = self.draft + [point]
            try:
                if len(points) == 2 and math.dist(*points) < 1e-8:
                    raise ValueError("顶点不能与端点重合，请重新选点")
                if len(points) == 3:
                    angle_degrees(points)
                    self.draft = []
                    self.angle_created.emit(points)
                else:
                    self.draft = points
            except ValueError as exc:
                self.message.emit(str(exc))
            self.update()
            return
        angles = sorted(self.visible_angles(), key=lambda r: r["id"] == self.selected_id, reverse=True)
        for record in angles:
            points = [self.to_screen(p) for p in record["points"]]
            for index, handle in enumerate(points):
                if math.hypot(position.x() - handle.x(), position.y() - handle.y()) <= 9:
                    self.select(record["id"])
                    self._drag = (record["id"], index, [p[:] for p in record["points"]])
                    return
            if min(self._distance(position, points[0], points[1]), self._distance(position, points[1], points[2])) <= 7:
                self.select(record["id"])
                return
        self.select("")

    def mouseMoveEvent(self, event):
        if self._drag is not None and self.editable:
            self._drag[2][self._drag[1]] = self.to_image(QPointF(event.pos()), clamp=True)
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag is not None:
            record_id, _, points = self._drag
            self._drag = None
            try:
                angle_degrees(points)
                self.angle_edited.emit(record_id, points)
            except ValueError as exc:
                self.message.emit(str(exc))
            self.update()
        else:
            super().mouseReleaseEvent(event)

    def _label(self, painter, position, text, color):
        bounds = painter.fontMetrics().boundingRect(text)
        image = self.image_rect()
        width, height = bounds.width() + 8, bounds.height() + 4
        x = max(image.left(), min(position.x(), image.right() - width))
        y = max(image.top(), min(position.y(), image.bottom() - height))
        rect = QRectF(x, y, width, height)
        painter.fillRect(rect, QColor(0, 0, 0, 185))
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignCenter, text)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.annotations_visible or self.image_rect().isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.image_rect())
        for record in self.visible_angles():
            source = self._drag[2] if self._drag and self._drag[0] == record["id"] else record["points"]
            self._draw_angle(painter, source, record["id"] == self.selected_id)
        if self.draft:
            points = [self.to_screen(p) for p in self.draft]
            painter.setPen(QPen(QColor("#ffd166"), 2))
            for point in points:
                painter.drawEllipse(point, 4, 4)
            if len(points) == 2:
                painter.drawLine(*points)
        if self.times is not None:
            for row, record in enumerate(self.visible_intervals()):
                delta = self.times[record["end"]] - self.times[record["start"]]
                text = f"第 {record['start'] + 1}–{record['end'] + 1} 帧  {delta:.3f} s"
                if self.estimated:
                    text += "（估算）"
                color = QColor("#ffd166" if record["id"] == self.selected_id else "#69dfca")
                rect = self.image_rect()
                self._label(painter, QPointF(rect.left() + 8, rect.top() + 8 + row * (painter.fontMetrics().height() + 8)), text, color)
        painter.end()

    def _draw_angle(self, painter, source, selected):
        points = [self.to_screen(p) for p in source]
        color = QColor("#ffd166" if selected else "#69dfca")
        painter.setPen(QPen(color, 2))
        painter.drawLine(points[0], points[1])
        painter.drawLine(points[1], points[2])
        if selected:
            for point in points:
                painter.drawEllipse(point, 5, 5)
        try:
            angle = angle_degrees(source)
        except ValueError:
            return
        a, b, c = points
        start = math.degrees(math.atan2(b.y() - a.y(), a.x() - b.x()))
        end = math.degrees(math.atan2(b.y() - c.y(), c.x() - b.x()))
        span = (end - start + 180) % 360 - 180
        radius = min(24, math.hypot(a.x() - b.x(), a.y() - b.y()) / 3,
                     math.hypot(c.x() - b.x(), c.y() - b.y()) / 3)
        painter.drawArc(QRectF(b.x() - radius, b.y() - radius, radius * 2, radius * 2), round(start * 16), round(span * 16))
        self._label(painter, b + QPointF(12, 12), f"{angle:.1f}°", color)

"""Interactive evidence charts and exact record lookup for report analysis."""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QPushButton, QAbstractItemView,
)

from reporting.models import EvidenceChart
from reporting.text import format_numeric_value
from ui.theme import PALETTE


_COLORS = ('#24b9c9', '#f0a44b', '#9a8ce4', '#82bc60')
_SIDES = {'left': '左', 'right': '右', 'unknown': '未知', None: '—'}


class EvidenceChartWidget(QWidget):
    def __init__(self, chart: EvidenceChart, pg, parent=None):
        super().__init__(parent)
        self.chart = chart
        self.pg = pg
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel(chart.title)
        title.setStyleSheet('font-weight:600; font-size:15px')
        header.addWidget(title)
        header.addStretch()
        self.kind = QComboBox()
        for label, value in (('逐条变化', 'time_series'), ('组内分布', 'side_distribution'), ('分组均值', 'segment_comparison')):
            self.kind.addItem(label, value)
        self.kind.setCurrentIndex(self.kind.findData(chart.chart_type))
        header.addWidget(self.kind)
        layout.addLayout(header)
        self.scope = QLabel(chart.grouping)
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.plot = pg.PlotWidget() if pg else None
        if self.plot:
            self.plot.setBackground(PALETTE['surface'])
            self.plot.setMinimumHeight(260)
            self.plot.setMaximumHeight(330)
            layout.addWidget(self.plot)
        self.stats = QLabel(' · '.join(f'{g.label} n={len(g.points)}，均值 {format_numeric_value(g.mean, chart.unit)}' for g in chart.groups))
        self.stats.setWordWrap(True)
        layout.addWidget(self.stats)
        self.records_button = QPushButton('查看参与分析的记录')
        self.records_button.setCheckable(True)
        layout.addWidget(self.records_button)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(('记录序号', '时间(s)', '侧别', chart.title + f' ({chart.unit})', '分组'))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMaximumHeight(240)
        self.rows = []
        for group in chart.groups:
            for point in group.points:
                row = self.table.rowCount()
                self.table.insertRow(row)
                values = (point.ordinal + 1,
                          '—' if point.timestamp_s is None else f'{point.timestamp_s:.3f}',
                          _SIDES[point.side], f'{point.value:.6g}', group.label)
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(str(value))
                    cell.setToolTip(point.record_ref)
                    cell.setData(Qt.UserRole, point.record_ref)
                    self.table.setItem(row, column, cell)
                self.rows.append((group.group_id, point.record_ref))
        self.table.resizeColumnsToContents()
        for column, minimum in enumerate((92, 90, 62, 180)):
            self.table.setColumnWidth(column, max(minimum, self.table.columnWidth(column)))
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.hide()
        layout.addWidget(self.table)
        self.records_button.toggled.connect(self.table.setVisible)
        self.kind.currentIndexChanged.connect(self.draw)
        self.draw()

    def draw(self):
        if self.plot is None:
            return
        self.plot.clear()
        chart = self.chart
        kind = self.kind.currentData()
        use_time = all(p.timestamp_s is not None for g in chart.groups for p in g.points)
        axis = self.plot.getAxis('left')
        self.plot.setLabel('left', chart.title, units=chart.unit)
        if hasattr(axis, 'setSIPrefixEnableRanges'):
            axis.setSIPrefixEnableRanges(())
        axis.enableAutoSIPrefix(False)
        self.plot.showGrid(x=True, y=True, alpha=.18)
        self.plot.getAxis('bottom').setTicks(None)
        self.plot.setLabel('bottom', '时间 (s)' if use_time else '记录序号')
        for index, group in enumerate(chart.groups):
            color = _COLORS[index % len(_COLORS)]
            if kind == 'segment_comparison':
                self.plot.addItem(self.pg.BarGraphItem(x=[index], height=[group.mean], width=.55, brush=color))
            points = []
            for position, point in enumerate(group.points):
                x = point.timestamp_s if use_time else point.ordinal + 1
                if kind != 'time_series':
                    x = index + ((position % 7) - 3) * .035
                points.append({'pos': (x, point.value), 'data': (group.group_id, point.record_ref)})
            if kind == 'time_series':
                self.plot.plot([p['pos'][0] for p in points], [p['pos'][1] for p in points], pen=self.pg.mkPen(color, width=1.5))
            scatter = self.pg.ScatterPlotItem(size=8, brush=color, pen=None)
            scatter.setData(points)
            scatter.sigClicked.connect(self.select_point)
            self.plot.addItem(scatter)
        if kind != 'time_series':
            self.plot.getAxis('bottom').setTicks([[(i, g.label) for i, g in enumerate(chart.groups)]])
            self.plot.setLabel('bottom', '分析分组')

    def select_point(self, _item, points, _event=None):
        if len(points) == 0:
            return
        key = points[0].data()
        row = self.rows.index(key)
        self.records_button.setChecked(True)
        self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(row, 0))


def chart_image(chart, pg):
    """Use the same plot widget for the static PDF evidence image."""
    widget = EvidenceChartWidget(chart, pg)
    widget.kind.hide()
    widget.records_button.hide()
    widget.setStyleSheet('background:white; color:#17344d;')
    if widget.plot:
        widget.plot.setBackground('white')
        for name in ('left', 'bottom'):
            axis = widget.plot.getAxis(name)
            axis.setPen('#536474')
            axis.setTextPen('#17344d')
    widget.resize(900, 360)
    widget.layout().activate()
    widget.ensurePolished()
    image = widget.grab().toImage()
    widget.deleteLater()
    return image

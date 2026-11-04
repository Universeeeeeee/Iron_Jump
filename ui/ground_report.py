"""Record-oriented ground report views; all values come from report snapshots."""
import math

from qtpy.QtCore import Qt, Signal, QTimer
from qtpy.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHeaderView,
    QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget, QSizePolicy,
)

from reporting.ground_bilateral import bilateral_html
from reporting.overground_running import REASONS
from reporting.recognized_gait import recognized_gait
from ui.theme import PALETTE, qss


METRICS = [('step_length_m', '单步距离', 'm'),
           ('step_time_s', '步间时间', 's'), ('contact_s', '接触时间', 's')]
SIDE_LABELS = {'left': '左', 'right': '右', 'unknown': '未知'}


def number(value):
    return '—' if value is None else f'{value:.3f}'


def record_table(headers):
    table = QTableWidget(0, len(headers))
    table.setObjectName('ReportDetailTable')
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def fill_row(table, index, values, tooltip=''):
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(Qt.AlignCenter)
        item.setToolTip(tooltip)
        table.setItem(index, column, item)


class GroundStepAnalysis(QWidget):
    contact_selected = Signal(object)
    locate_requested = Signal(object)
    raw_requested = Signal()

    def __init__(self, summary, plot_module=None, parent=None):
        super().__init__(parent)
        self.setObjectName('GroundStepAnalysis')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.pg = plot_module
        self.data = recognized_gait(summary)
        contacts = {(c.get('epoch', 0), c['id']): c for c in summary.get('contacts', [])}
        self.rows = [dict(row, index=i + 1,
                          side=contacts.get((row['epoch'], row['contact_id']), {}).get('side', 'unknown'))
                     for i, row in enumerate(self.data['rows'])]
        self.selected_contact_id = None
        self.setStyleSheet(qss('''
            QWidget#GroundStepAnalysis { background: ${sidebar}; }
            QFrame#GroundMetricCard, QFrame#GroundSelection {
                background: ${surface}; border: 1px solid ${border_card}; border-radius: 7px;
            }
            QLabel { color: ${text}; background: transparent; border: none; }
            QLabel#GroundValue { font-size: 20px; font-weight: 600; }
            QLabel#GroundHint { color: ${text_muted}; font-size: 12px; }
        '''))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        cards = QHBoxLayout()
        measurements = [('已识别落脚', f"{len(self.rows)} 次", '有效落脚事件')]
        for key, label, unit in METRICS:
            values = [self.metric_value(row, key) for row in self.rows]
            valid = [v for v in values if v is not None]
            measurements.append((label, number(sum(valid) / len(valid) if valid else None) + ' ' + unit,
                                 f'均值 · n = {len(valid)}'))
        for label, value, hint in measurements:
            card = QFrame()
            card.setObjectName('GroundMetricCard')
            box = QVBoxLayout(card)
            box.setContentsMargins(12, 9, 12, 9)
            box.addWidget(QLabel(label))
            amount = QLabel(value)
            amount.setObjectName('GroundValue')
            box.addWidget(amount)
            note = QLabel(hint)
            note.setObjectName('GroundHint')
            box.addWidget(note)
            cards.addWidget(card, 1)
        layout.addLayout(cards)

        middle = QHBoxLayout()
        chart = QVBoxLayout()
        controls = QHBoxLayout()
        controls.addWidget(QLabel('逐步变化'))
        controls.addStretch()
        self.metric_selector = QComboBox()
        self.metric_selector.setObjectName('ReportFilterCombo')
        for key, label, unit in METRICS:
            self.metric_selector.addItem(label, key)
        controls.addWidget(self.metric_selector)
        chart.addLayout(controls)
        self.plot = self.pg.PlotWidget() if self.pg else None
        if self.plot is not None:
            self.plot.setBackground(PALETTE['surface'])
            self.plot.setMinimumHeight(150)
            self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
            self.plot.showGrid(x=False, y=True, alpha=.12)
            self.plot.setMenuEnabled(False)
            self.plot.setMouseEnabled(x=False, y=False)
            self.plot.setLabel('bottom', '落脚序号')
            chart.addWidget(self.plot, 1)
        else:
            chart.addWidget(QLabel('趋势图不可用，可在下方查看逐条数据。'), 1)
        self.chart_note = QLabel()
        self.chart_note.setObjectName('GroundHint')
        chart.addWidget(self.chart_note)
        middle.addLayout(chart, 2)

        selection = QFrame()
        selection.setObjectName('GroundSelection')
        selection.setMinimumWidth(220)
        selection.setMaximumWidth(320)
        box = QVBoxLayout(selection)
        self.selection_title = QLabel('暂无已确认落脚')
        self.selection_title.setStyleSheet('font-size: 17px; font-weight: 600;')
        box.addWidget(self.selection_title)
        grid = QGridLayout()
        self.values = {}
        for i, (key, label, unit) in enumerate(METRICS + [('position_m', '参考位置', 'm')]):
            grid.addWidget(QLabel(label), i, 0)
            self.values[key] = QLabel('—')
            self.values[key].setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(self.values[key], i, 1)
        box.addLayout(grid)
        self.selection_note = QLabel()
        self.selection_note.setWordWrap(True)
        self.selection_note.setObjectName('GroundHint')
        box.addWidget(self.selection_note)
        box.addStretch()
        actions = QHBoxLayout()
        self.locate_button = QPushButton('定位回放')
        self.locate_button.setEnabled(False)
        self.locate_button.clicked.connect(self._locate)
        actions.addWidget(self.locate_button)
        raw = QPushButton('原始记录')
        raw.clicked.connect(self.raw_requested.emit)
        actions.addWidget(raw)
        box.addLayout(actions)
        middle.addWidget(selection, 1)
        layout.addLayout(middle, 3)

        row = QHBoxLayout()
        row.addWidget(QLabel('逐条记录'))
        row.addStretch()
        self.record_filter = QComboBox()
        self.record_filter.setObjectName('ReportFilterCombo')
        for label, value in [('全部记录', 'all'), ('指标不完整', 'incomplete'),
                             ('左脚', 'left'), ('右脚', 'right'), ('左右未知', 'unknown')]:
            self.record_filter.addItem(label, value)
        row.addWidget(self.record_filter)
        layout.addLayout(row)
        self.table = record_table(['落脚', '脚', '单步距离 (m)', '步间 (s)', '接触 (s)', '指标状态'])
        self.table.setMinimumHeight(170)
        layout.addWidget(self.table, 2)
        self.table.itemSelectionChanged.connect(self._table_selected)
        self.record_filter.currentIndexChanged.connect(self._filter_records)
        self.metric_selector.currentIndexChanged.connect(self._draw_plot)
        self._filter_records()
        self._draw_plot()

    @staticmethod
    def metric_value(row, key):
        if key == 'contact_s' and not row['contact_included']:
            return None
        return row.get(key)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._scroll_selected)

    def _scroll_selected(self):
        if self.table.currentItem() is not None:
            self.table.scrollToItem(self.table.currentItem(), QAbstractItemView.PositionAtCenter)

    def clear_selection(self):
        if self.selected_contact_id is None:
            return
        self.selected_contact_id = None
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.blockSignals(False)
        self.selection_title.setText('尚未落脚')
        for value in self.values.values():
            value.setText('—')
        self.selection_note.clear()
        self.locate_button.setEnabled(False)
        self._draw_plot()

    def _filter_records(self):
        choice = self.record_filter.currentData()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            incomplete = any(self.metric_value(row, key) is None for key, _, _ in METRICS)
            fill_row(self.table, i, [f"#{row['index']:02d}", SIDE_LABELS.get(row['side'], '未知'),
                *[number(self.metric_value(row, key)) for key, _, _ in METRICS],
                '指标不完整' if incomplete else '完整'], row['relation_note'] + '；' + row['contact_basis'])
            visible = (choice == 'all' or choice == 'incomplete' and incomplete or choice == row['side'])
            self.table.setRowHidden(i, not visible)
        self.table.blockSignals(False)
        # Selection is a contact identity; filtering never renumbers footfalls.
        if self.selected_contact_id is not None:
            index = next(i for i, r in enumerate(self.rows) if r['contact_id'] == self.selected_contact_id)
            self.table.blockSignals(True)
            self.table.selectRow(index)
            self.table.blockSignals(False)

    def _table_selected(self):
        index = self.table.currentRow()
        if index >= 0:
            self.select_contact(self.rows[index]['contact_id'])

    def select_contact(self, contact_id):
        index = next((i for i, r in enumerate(self.rows) if r['contact_id'] == contact_id), None)
        if index is None:
            return
        if self.table.isRowHidden(index):
            self.record_filter.setCurrentIndex(0)
        if self.selected_contact_id == contact_id:
            return
        row = self.rows[index]
        self.selected_contact_id = contact_id
        self.table.blockSignals(True)
        self.table.selectRow(index)
        self.table.scrollToItem(self.table.item(index, 0))
        self.table.blockSignals(False)
        self.selection_title.setText(f"选中落脚 #{row['index']:02d} · {SIDE_LABELS.get(row['side'], '未知')}")
        for key, _, unit in METRICS + [('position_m', '参考位置', 'm')]:
            value = self.metric_value(row, key)
            self.values[key].setText(number(value) + (' ' + unit if value is not None else ''))
        references = {'first_observed_contact_center_v1': '首次有效接触中心', 'legacy_stance_center': '支撑相中心',
                      'legacy_stable_toe': '稳定脚尖代理', 'unavailable': '位置参考缺失'}
        reference = references.get(row['position_basis'], row['position_basis'])
        self.selection_note.setText(row['relation_note'] + '；' + row['contact_basis'] + '\n' + reference)
        self.locate_button.setEnabled(row.get('relative_time_s') is not None)
        self._draw_plot()
        self.contact_selected.emit(row)

    def _locate(self):
        row = next((r for r in self.rows if r['contact_id'] == self.selected_contact_id), None)
        if row is not None:
            self.locate_requested.emit(row)

    def _draw_plot(self):
        key, label, unit = METRICS[self.metric_selector.currentIndex()]
        values = [self.metric_value(row, key) for row in self.rows]
        valid = [value for value in values if value is not None]
        mean = sum(valid) / len(valid) if valid else None
        self.chart_note.setText(f'有效样本 n = {len(valid)} · 均值 {number(mean)} {unit}' if valid
                               else '该指标暂无有效样本')
        if self.plot is None:
            return
        self.plot.clear()
        axis = self.plot.getAxis('left')
        self.plot.setLabel('left', label, units=unit)
        # Newer pyqtgraph also scales labels from setLabel, independently of autoSIPrefix.
        if hasattr(axis, 'setSIPrefixEnableRanges'):
            axis.setSIPrefixEnableRanges(())
        axis.enableAutoSIPrefix(False)
        if not valid:
            return
        self.plot.plot([r['index'] for r in self.rows],
                       [v if v is not None else math.nan for v in values], connect='finite',
                       pen=self.pg.mkPen('#67dce9', width=2))
        points = self.pg.ScatterPlotItem(size=9, brush='#67dce9', pen=None)
        points.setData([{'pos': (row['index'], value), 'data': row['contact_id']}
                        for row, value in zip(self.rows, values) if value is not None])
        points.sigClicked.connect(lambda item, spots, event: self.select_contact(spots[0].data()))
        self.plot.addItem(points)
        self.plot.addItem(self.pg.InfiniteLine(mean, angle=0,
                          pen=self.pg.mkPen('#67dce9', style=Qt.DashLine)))
        selected = [(row['index'], value) for row, value in zip(self.rows, values)
                    if row['contact_id'] == self.selected_contact_id and value is not None]
        if selected:
            self.plot.plot([selected[0][0]], [selected[0][1]], pen=None,
                           symbol='o', symbolSize=13, symbolBrush=PALETTE['accent'], symbolPen=None)
        self.plot.setXRange(.5, max(1.5, len(self.rows) + .5), padding=0)
        # Include zero so a narrow automatic range cannot exaggerate tiny changes.
        self.plot.setYRange(0, max(valid) * 1.15 or 1, padding=0)


class GroundCycleAnalysis(QWidget):
    contact_selected = Signal(object)

    def __init__(self, summary, parent=None):
        super().__init__(parent)
        self.setObjectName('ReportDetailPage')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        switch = QComboBox()
        switch.setObjectName('ReportFilterCombo')
        switch.addItems(['周期记录', '左右统计'])
        layout.addWidget(switch, 0, Qt.AlignLeft)
        pages = QStackedWidget()
        layout.addWidget(pages)
        switch.currentIndexChanged.connect(pages.setCurrentIndex)
        self.table = record_table(['周期', '脚', '接触编号', '周期 (s)', '跨步长 (m)',
                                   '支撑 (s)', '摆动 (s)', '指标说明'])
        self.rows = summary.get('bilateral', {}).get('records', {}).get('cycles', [])
        if 'bilateral' not in summary:
            self.rows = []
            for row in summary.get('cycles', []):
                metrics = {}
                for key, source in [('gait_cycle_s', 'duration_s'), ('stride_length_m', 'length_m'),
                                    ('stance_phase_s', 'contact_s'), ('swing_phase_s', 'swing_s')]:
                    value = row.get(source)
                    metrics[key] = value if isinstance(value, dict) else {
                        'value': value, 'valid': value is not None,
                        'missing_reason': None if value is not None else 'historical_metric_not_recorded'}
                self.rows.append({'side': row.get('side', 'unknown'),
                                  'contact_ids': [row[key] for key in ('from_id', 'to_id') if key in row],
                                  'metrics': metrics})
        self.table.setRowCount(len(self.rows))
        keys = ['gait_cycle_s', 'stride_length_m', 'stance_phase_s', 'swing_phase_s']
        for i, row in enumerate(self.rows):
            metrics = row['metrics']
            notes = list(dict.fromkeys(REASONS.get(m['missing_reason'], m['missing_reason'])
                                      for m in metrics.values() if not m['valid']))
            notes = [{'entry_support_not_observed': '入口支撑阶段未完整观测',
                      'historical_metric_not_recorded': '历史记录未包含此指标'}.get(note, note) for note in notes]
            fill_row(self.table, i, [f'#{i + 1:02d}', SIDE_LABELS.get(row['side'], '未知'),
                     ' → '.join(str(cid) for cid in row['contact_ids']) or '—',
                     *[number(metrics.get(key, {}).get('value') if metrics.get(key, {}).get('valid') else None)
                       for key in keys], '；'.join(notes) or '完整'])
        pages.addWidget(self.table)
        if not self.rows:
            layout.addWidget(QLabel('暂无可用周期记录；历史报告的已有数据可在原始记录中查看。'))
        browser = QTextBrowser()
        browser.setHtml(bilateral_html(summary))
        pages.addWidget(browser)
        self.table.itemSelectionChanged.connect(self._select)

    def _select(self):
        index = self.table.currentRow()
        if index >= 0 and self.rows[index]['contact_ids']:
            self.contact_selected.emit(self.rows[index]['contact_ids'][0])

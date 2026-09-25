"""
param_panel.py — Jump Test 参数配置面板

动态生成表单控件，处理 stop_type 联动显隐，
对外提供 get_config() -> TestConfig 接口。

使用局部深色 QSS，避免依赖主窗口的全局 Dayu 主题:
  - QLabel:       标签和分组标题
  - MSpinBox:     整数输入
  - MTimeEdit:    时间输入 (mm:ss)
  - MSwitch:      布尔开关
  - MSectionItem: 折叠面板
  - QComboBox:    枚举选择 (标准控件, 避免 MComboBox 点击问题)
"""

from __future__ import annotations

from qtpy.QtCore import QSignalBlocker, Signal, Qt, QTime
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox,
    QDoubleSpinBox, QLabel, QSizePolicy,
)

from dayu_widgets.spin_box import MSpinBox, MTimeEdit
from dayu_widgets.switch import MSwitch
from dayu_widgets.collapse import MSectionItem

from config.param_schema import ParamSchema, ParamDef, get_schema
from config.test_config import AnyTestConfig, TestConfig, config_from_dict


PARAM_PANEL_QSS = """
QWidget#ParamPanelRoot {
    background: #121923;
    color: #e7ebf2;
}
QLabel#ParamSectionTitle {
    color: #f2f5fa;
    font-size: 14px;
    font-weight: 700;
    padding: 2px 0 6px 2px;
}
QWidget#ParamFormRow {
    background: #171f2b;
    border: 1px solid #293442;
    border-radius: 8px;
}
QLabel#ParamFieldLabel {
    color: #9da8b8;
    background: transparent;
    border: none;
    font-size: 13px;
}
QComboBox,
QSpinBox,
QDoubleSpinBox,
QTimeEdit {
    min-height: 34px;
    border: 1px solid #354151;
    border-radius: 6px;
    background: #1a2230;
    color: #e7ebf2;
    padding: 0 9px;
    font-size: 13px;
    selection-background-color: #ff7a00;
}
QComboBox:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QTimeEdit:hover {
    border-color: #59677a;
}
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QTimeEdit:focus {
    border-color: #ff7a00;
}
QComboBox QAbstractItemView {
    background: #1a2230;
    color: #e7ebf2;
    border: 1px solid #354151;
    selection-background-color: #273446;
}
QAbstractSpinBox::up-button,
QAbstractSpinBox::down-button {
    width: 22px;
    background: #202a38;
    border-left: 1px solid #354151;
}
QWidget#ParamFilterSection {
    background: transparent;
    color: #d9dee8;
}
QWidget#ParamFilterSection QWidget#title {
    min-height: 34px;
    background: #151d28;
    border: 1px solid #293442;
    border-radius: 6px;
}
QWidget#ParamFilterSection QWidget#title QLabel {
    color: #cfd6e3;
    background: transparent;
    border: none;
}
QWidget#ParamFilterContent {
    background: transparent;
}
"""


class ParamPanel(QWidget):
    """
    动态参数配置面板。

    根据 ParamSchema 和当前 test_type 生成表单，
    处理 stop_type / metronome_enabled 联动显隐。
    """

    config_changed = Signal()
    """参数变更信号。任何参数控件值变化时发射。"""

    # 各测试类型 Layer2 参数的创建顺序
    _LAYER2_ORDER: dict[str, list[str]] = {
        "Jump Test": [
            "start_type", "start_position", "stop_type",
            "finish_position", "number_of_jumps", "test_length",
            "starting_foot",
        ],
        "Sprint and Gait Test": ["stop_type", "starting_foot"],
        "Overground Running Test": ["stop_type", "starting_foot"],
        "Treadmill Gait Test": [
            "stop_type", "test_length", "treadmill_speed", "direction",
        ],
        "Treadmill Running Test": [
            "stop_type", "test_length", "treadmill_speed", "direction",
        ],
    }

    # 受 stop_type 联动影响的字段
    _CONDITIONAL_FIELDS = ["finish_position", "number_of_jumps", "test_length"]

    # 各测试类型 Layer3 滤波参数的创建顺序
    _LAYER3_ORDER: dict[str, list[str]] = {
        "Sprint and Gait Test": ["min_contact_time"],
        "Overground Running Test": ["min_contact_time"],
        "Jump Test": [
            "min_contact_time", "min_flight_time", "max_flight_time",
            "flight_time_review_threshold",
        ],
        "Treadmill Gait Test": [
            "min_contact_time", "min_flight_time", "max_flight_time",
            "step_length_calculation", "min_step_length", "min_foot_length",
            "filter_gaitr_in", "filter_gaitr_out", "automatic_data_filter",
        ],
        "Treadmill Running Test": [
            "min_contact_time", "min_flight_time", "max_flight_time",
            "step_length_calculation", "min_gap_between_feet", "min_foot_length",
            "filter_gaitr_in", "filter_gaitr_out",
        ],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ParamPanelRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(PARAM_PANEL_QSS)

        self._schema: ParamSchema = get_schema()
        self._test_type: str = "Jump Test"

        # 参数名 → 输入控件 (QComboBox / MSpinBox / MTimeEdit / MSwitch)
        self._widgets: dict[str, QWidget] = {}
        # 参数名 → 整行容器 QWidget (用于 show/hide)
        self._rows: dict[str, QWidget] = {}

        self._filter_section: MSectionItem | None = None
        self._optional_section: MSectionItem | None = None

        self._build_ui()
        self._connect_signals()
        self._refresh_visibility()

    # ==================================================================
    #  公共方法
    # ==================================================================

    def get_config(self) -> AnyTestConfig:
        """
        收集所有控件当前值，构建对应测试类型的配置对象。

        利用 config_from_dict() 根据 test_type 自动分发到正确的 Config 类
        (TestConfig / TreadmillGaitConfig / TreadmillRunningConfig)。
        不可见的条件字段设为 None。只传递当前 test_type 适用的参数。
        """
        values = self._current_values()
        test_type = self._test_type

        # 获取当前可见参数（同时过滤 applicable_tests 和 visibility_condition）
        visible_params = self._schema.get_visible_params(test_type, values)
        visible_names = {p.name for p in visible_params}

        # 获取当前 test_type 适用的所有参数（仅 applicable_tests 过滤）
        applicable = self._schema.visible_params_for_test(test_type)
        applicable_names = {p.name for p in applicable}

        # 构建配置 dict: 仅包含 applicable 且可见的参数 + test_type
        config_data: dict[str, object] = {"test_type": test_type}
        for name in values:
            if name not in applicable_names:
                continue  # 跳过不适用的参数（如 start_type 对 treadmill）
            if name in visible_names:
                config_data[name] = values[name]
            else:
                config_data[name] = None

        return config_from_dict(config_data)

    def set_config(self, config: AnyTestConfig) -> None:
        """从 TestConfig 反向填充控件值。用于加载历史配置。"""
        mapping = config.to_dict()
        target_test_type = config.test_type

        test_type_widget = self._widgets.get("test_type")
        if isinstance(test_type_widget, QComboBox):
            blocker = QSignalBlocker(test_type_widget)
            try:
                idx = test_type_widget.findData(target_test_type)
                if idx >= 0:
                    test_type_widget.setCurrentIndex(idx)
            finally:
                del blocker

        self._test_type = target_test_type
        self._rebuild_mode_fields()

        for name, widget in list(self._widgets.items()):
            if name == "test_type":
                continue
            val = mapping.get(name)
            if val is None:
                continue

            if isinstance(widget, QComboBox):
                idx = widget.findText(str(val))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, MSpinBox):
                widget.setValue(int(val))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(val))
            elif isinstance(widget, MTimeEdit):
                # val 格式 "mm:ss"
                parts = str(val).split(":")
                if len(parts) == 2:
                    widget.setTime(QTime(0, int(parts[0]), int(parts[1])))
            elif isinstance(widget, MSwitch):
                widget.setChecked(bool(val))

        self._refresh_visibility()

    def set_test_type(self, test_type: str) -> None:
        """切换测试类型并重建手动配置字段。"""
        if test_type == self._test_type:
            return

        test_type_widget = self._widgets.get("test_type")
        if not isinstance(test_type_widget, QComboBox):
            return

        idx = test_type_widget.findData(test_type)
        if idx < 0:
            return

        blocker = QSignalBlocker(test_type_widget)
        try:
            test_type_widget.setCurrentIndex(idx)
        finally:
            del blocker

        self._test_type = test_type
        self._rebuild_mode_fields()
        self._refresh_visibility()

    def set_enabled(self, enabled: bool) -> None:
        """锁定/解锁面板。测试运行中调用 set_enabled(False)。"""
        for widget in self._widgets.values():
            widget.setEnabled(enabled)

    # ==================================================================
    #  UI 构建
    # ==================================================================

    def _build_ui(self):
        """构建完整面板 UI 框架: Layer1 + 动态 Layer2/3/4 容器。"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ===== 基础配置 =====
        section_title = QLabel("基础配置")
        section_title.setObjectName("ParamSectionTitle")
        main_layout.addWidget(section_title)

        # 测试模式：独占整行
        test_type_combo = self._create_enum_widget("test_type")
        row = self._create_form_row("测试模式", test_type_combo)
        main_layout.addWidget(row)

        # Layer2 参数：2 列网格（容器）
        self._basic_grid = QGridLayout()
        self._basic_grid.setSpacing(10)
        main_layout.addLayout(self._basic_grid)

        # ===== Layer 3: 滤波参数 (折叠, 2 列网格) =====
        self._filter_container = QWidget()
        self._filter_container.setObjectName("ParamFilterContent")
        self._filter_grid = QGridLayout(self._filter_container)
        self._filter_grid.setContentsMargins(4, 4, 4, 4)
        self._filter_grid.setSpacing(10)

        self._filter_section = MSectionItem(
            title="滤波参数", widget=self._filter_container, expand=False
        )
        self._filter_section.setObjectName("ParamFilterSection")
        main_layout.addWidget(self._filter_section)

        # ===== Layer 4: 可选参数 (折叠, 2 列网格) =====
        optional_container = QWidget()
        optional_grid = QGridLayout(optional_container)
        optional_grid.setContentsMargins(4, 4, 4, 4)
        optional_grid.setSpacing(10)

        # 节拍器开关
        metro_switch = self._create_switch_widget()
        row_metro = self._create_form_row("节拍器", metro_switch)
        self._widgets["metronome_enabled"] = metro_switch
        self._rows["metronome_enabled"] = row_metro
        optional_grid.addWidget(row_metro, 0, 0)

        # 节拍 BPM
        bpm_def = self._schema.get_param_def("metronome_bpm")
        bpm_spinbox = self._create_int_widget("metronome_bpm", bpm_def)
        row_bpm = self._create_form_row("节拍 BPM", bpm_spinbox)
        optional_grid.addWidget(row_bpm, 0, 1)

        self._optional_section = MSectionItem(
            title="可选参数", widget=optional_container, expand=False
        )
        main_layout.addWidget(self._optional_section)
        self._optional_section.hide()

        # ===== 弹性空间 =====
        main_layout.addStretch()

        # 初始构建模式字段
        self._rebuild_mode_fields()

    # ==================================================================
    #  动态模式字段重建
    # ==================================================================

    def _on_test_type_changed(self, text: str) -> None:
        """test_type 变更 → 更新 _test_type 并重建模式字段。"""
        self._test_type = self._widgets["test_type"].currentData() or text
        self._rebuild_mode_fields()
        self._refresh_visibility()
        self.config_changed.emit()

    def _rebuild_mode_fields(self):
        """清除并重建 Layer2 和 Layer3 的模式相关控件。"""
        test_type = self._test_type

        # ---- 清除旧控件 ----
        self._remove_dynamic_widgets()
        self._clear_grid(self._basic_grid)
        self._clear_grid(self._filter_grid)

        # ---- 重建 Layer2 ----
        order = self._LAYER2_ORDER.get(test_type, [])
        applicable_names = {
            p.name for p in self._schema.get_params_for_test(test_type)
        }
        self._basic_grid_pos = 0
        for param_name in order:
            if param_name not in applicable_names:
                continue
            param_def = self._schema.get_param_def(param_name)
            if param_def is None:
                continue
            widget = self._create_widget_for_param(param_name, param_def)
            if widget is None:
                continue
            display = (
                param_def.display_name.split(" ")[0]
                if param_def.display_name
                else param_name
            )
            card = self._create_form_row(display, widget)
            self._rows[param_name] = card
            r, c = divmod(self._basic_grid_pos, 2)
            self._basic_grid.addWidget(card, r, c)
            self._basic_grid_pos += 1

        # ---- 重建 Layer3 ----
        filter_order = self._LAYER3_ORDER.get(test_type, [])
        pos = 0
        for param_name in filter_order:
            if param_name not in applicable_names:
                continue
            param_def = self._schema.get_param_def(param_name)
            if param_def is None:
                continue
            widget = self._create_widget_for_param(param_name, param_def)
            display = (
                param_def.display_name.split(" ")[0]
                if param_def.display_name
                else param_name
            )
            unit_text = f" ({param_def.unit})" if param_def.unit else ""
            card = self._create_form_row(display + unit_text, widget)
            r, c = divmod(pos, 2)
            self._filter_grid.addWidget(card, r, c)
            pos += 1

        # ---- 重建信号连接 ----
        self._connect_stop_type_signal()
        self._connect_widget_signals()

    def _remove_dynamic_widgets(self):
        """移除所有非持久化的控件引用。"""
        for param_name in list(self._rows.keys()):
            if param_name == "metronome_enabled":
                continue
            self._rows.pop(param_name, None)
        for param_name in list(self._widgets.keys()):
            if param_name in ("test_type", "metronome_enabled", "metronome_bpm"):
                continue
            self._widgets.pop(param_name, None)

    @staticmethod
    def _clear_grid(grid: QGridLayout):
        """移除 QGridLayout 中的所有子控件。"""
        while grid.count():
            item = grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _connect_stop_type_signal(self):
        """连接 stop_type 的 currentTextChanged 信号。"""
        if "stop_type" in self._widgets:
            w = self._widgets["stop_type"]
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._on_stop_type_changed)

    def _connect_widget_signals(self):
        """连接所有动态控件 → config_changed 统一通知。"""
        for name, widget in self._widgets.items():
            if name in ("test_type",):
                continue
            if isinstance(widget, QComboBox):
                if name == "stop_type":
                    continue  # 联动信号已单独连接
                widget.currentTextChanged.connect(
                    lambda _: self.config_changed.emit()
                )
            elif isinstance(widget, MSpinBox):
                widget.valueChanged.connect(
                    lambda _: self.config_changed.emit()
                )
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(
                    lambda _: self.config_changed.emit()
                )
            elif isinstance(widget, MTimeEdit):
                widget.timeChanged.connect(
                    lambda _: self.config_changed.emit()
                )
            elif isinstance(widget, MSwitch):
                widget.toggled.connect(
                    lambda _: self.config_changed.emit()
                )

    # ==================================================================
    #  控件创建
    # ==================================================================

    def _create_form_row(self, label_text: str, widget: QWidget) -> QWidget:
        """创建 FormRow: 卡片风格，标签在上、控件在下。"""
        row = QWidget()
        row.setObjectName("ParamFormRow")

        layout = QVBoxLayout(row)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("ParamFieldLabel")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(label)
        layout.addWidget(widget)

        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setMinimumHeight(68)
        return row

    def _create_widget_for_param(self, param_name: str, param_def: ParamDef) -> QWidget | None:
        """根据参数类型分派创建对应的控件。"""
        if param_def.param_type == "enum":
            widget = self._create_enum_widget(param_name)
        elif param_def.param_type == "integer":
            widget = self._create_int_widget(param_name, param_def)
        elif param_def.param_type == "float":
            widget = self._create_float_widget(param_name, param_def)
        elif param_def.param_type == "string" and param_name == "test_length":
            widget = self._create_time_widget()
        else:
            return None  # 不支持的类型

        self._widgets[param_name] = widget
        return widget

    def _create_enum_widget(self, param_name: str) -> QComboBox:
        """为枚举参数创建 QComboBox，选项从 schema 获取。"""
        combo = QComboBox()
        values = self._schema.get_enum_values(param_name, self._test_type)
        if param_name == "test_type":
            values = [
                test_type
                for test_type in self._LAYER2_ORDER
                if test_type in values
            ]
        if param_name == "test_type":
            for value in values:
                combo.addItem("地面跑步" if value == "Overground Running Test" else value, value)
        else:
            combo.addItems(values)

        # 设置默认值
        param_def = self._schema.get_param_def(param_name)
        default = self._default_for_param(param_name, param_def)
        if default is not None:
            idx = combo.findText(str(default))
            if idx >= 0:
                combo.setCurrentIndex(idx)

        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 存入 _widgets（test_type 在 _build_ui 中单独处理）
        self._widgets[param_name] = combo
        return combo

    def _create_int_widget(self, param_name: str, param_def: ParamDef | None) -> MSpinBox:
        """为整数参数创建 MSpinBox，范围和默认值从 ParamDef 读取。"""
        spinbox = MSpinBox()
        spinbox.setKeyboardTracking(False)  # 避免键盘输入中间态触发 valueChanged

        # 解析范围
        lo, hi = 0, 9999
        if param_def and param_def.range_str and not param_def.range_str.startswith("{"):
            parts = param_def.range_str.split("-")
            if len(parts) == 2:
                try:
                    lo, hi = int(parts[0]), int(parts[1])
                except ValueError:
                    pass

        # 特殊处理: 当 schema default 低于 range 下限时（如 automatic_data_filter
        # 的 default=0, range=10-90），扩展下限以容纳默认值。
        default = self._default_for_param(param_name, param_def)
        if default is not None:
            try:
                default_val = int(default)
                if default_val < lo:
                    lo = default_val
            except (ValueError, TypeError):
                pass

        spinbox.setRange(lo, hi)

        # 设置默认值
        if default is not None:
            try:
                spinbox.setValue(int(default))
            except (ValueError, TypeError):
                pass

        spinbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._widgets[param_name] = spinbox
        return spinbox

    def _create_float_widget(self, param_name: str, param_def: ParamDef) -> QDoubleSpinBox:
        """为浮点参数创建 QDoubleSpinBox，范围和默认值从 ParamDef 和 dataclass 读取。"""
        spinbox = QDoubleSpinBox()
        spinbox.setKeyboardTracking(False)

        # 解析范围
        lo, hi = 0.0, 9999.0
        if param_def.range_str and not param_def.range_str.startswith("{"):
            parts = param_def.range_str.split("-")
            if len(parts) == 2:
                try:
                    lo, hi = float(parts[0]), float(parts[1])
                except ValueError:
                    pass
        spinbox.setRange(lo, hi)

        # 步进
        if param_def.step is not None:
            spinbox.setSingleStep(param_def.step)
        else:
            spinbox.setSingleStep(0.1)

        # 小数位数
        spinbox.setDecimals(1)

        # 设置默认值：优先 schema default，否则从 dataclass 字段默认值获取
        default = self._default_for_param(param_name, param_def)
        if default is None and param_name != "treadmill_speed":
            # automatic_data_filter 特殊处理：range 10-90 但 default=0（关闭）
            # 从 dataclass 获取默认值
            default = self._get_dataclass_default(param_name)

        if default is not None:
            try:
                spinbox.setValue(float(default))
            except (ValueError, TypeError):
                pass

        spinbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._widgets[param_name] = spinbox
        return spinbox

    def _default_for_param(self, param_name: str, param_def: ParamDef | None) -> object | None:
        """Return schema default, resolving per-test defaults when present."""
        if param_def is None:
            return None
        default = param_def.default
        if isinstance(default, dict):
            return default.get(self._test_type)
        return default

    def _get_dataclass_default(self, param_name: str) -> object | None:
        """从当前 test_type 对应的配置 dataclass 读取字段默认值。"""
        test_type = self._test_type
        try:
            if test_type == "Overground Running Test":
                from config.overground_running_config import OvergroundRunningConfig
                fields = OvergroundRunningConfig.__dataclass_fields__
            elif test_type == "Sprint and Gait Test":
                from config.walking_config import WalkingConfig
                fields = WalkingConfig.__dataclass_fields__
            elif test_type == "Treadmill Gait Test":
                from config.treadmill_config import TreadmillGaitConfig
                fields = TreadmillGaitConfig.__dataclass_fields__
            elif test_type == "Treadmill Running Test":
                from config.treadmill_config import TreadmillRunningConfig
                fields = TreadmillRunningConfig.__dataclass_fields__
            else:
                from config.test_config import TestConfig
                fields = TestConfig.__dataclass_fields__
            field = fields.get(param_name)
            if field and field.default is not None and not isinstance(field.default, type):
                return field.default
        except (ImportError, AttributeError):
            pass
        return None

    def _create_time_widget(self) -> MTimeEdit:
        """为 test_length 创建 MTimeEdit，格式 mm:ss。"""
        time_edit = MTimeEdit()
        time_edit.setDisplayFormat("mm:ss")
        time_edit.setTime(QTime(0, 1, 0))  # 默认 01:00

        time_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._widgets["test_length"] = time_edit
        return time_edit

    def _create_switch_widget(self) -> MSwitch:
        """为布尔参数创建 MSwitch。"""
        switch = MSwitch()
        switch.setChecked(False)
        return switch

    # ==================================================================
    #  联动逻辑
    # ==================================================================

    def _on_stop_type_changed(self, text: str) -> None:
        """stop_type 变更 → 刷新条件字段的 show/hide。"""
        current_vals = self._current_values()
        current_vals["stop_type"] = text  # 确保用最新值

        visible_params = self._schema.get_visible_params(self._test_type, current_vals)
        visible_names = {p.name for p in visible_params}

        for field_name in self._CONDITIONAL_FIELDS:
            if field_name in self._rows:
                if field_name in visible_names:
                    self._rows[field_name].show()
                else:
                    self._rows[field_name].hide()

        self.config_changed.emit()

    def _on_metronome_changed(self, checked: bool) -> None:
        """metronome_enabled 变更 → metronome_bpm 行的 show/hide。"""
        if "metronome_bpm" in self._rows:
            if checked:
                self._rows["metronome_bpm"].show()
            else:
                self._rows["metronome_bpm"].hide()

        self.config_changed.emit()

    def _refresh_visibility(self) -> None:
        """根据当前值刷新所有条件字段显隐。初始化和 test_type 切换时调用。"""
        # 1. stop_type 联动
        stop_type = ""
        if "stop_type" in self._widgets:
            w = self._widgets["stop_type"]
            if isinstance(w, QComboBox):
                stop_type = w.currentText()
        self._on_stop_type_changed(stop_type)

        # 2. metronome 联动
        metro_on = False
        if "metronome_enabled" in self._widgets:
            w = self._widgets["metronome_enabled"]
            if isinstance(w, MSwitch):
                metro_on = w.isChecked()
        self._on_metronome_changed(metro_on)

    def _connect_signals(self) -> None:
        """连接持久信号（test_type 切换、metronome 联动）。

        动态控件的信号（stop_type、模式字段值变更）
        由 _rebuild_mode_fields() → _connect_stop_type_signal() + _connect_widget_signals() 管理。
        """
        # 1. test_type 切换 → 重建模式字段
        if "test_type" in self._widgets:
            w = self._widgets["test_type"]
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._on_test_type_changed)

        # 2. metronome 联动
        if "metronome_enabled" in self._widgets:
            w = self._widgets["metronome_enabled"]
            if isinstance(w, MSwitch):
                w.toggled.connect(self._on_metronome_changed)

    # ==================================================================
    #  值收集
    # ==================================================================

    def _current_values(self) -> dict:
        """收集所有控件当前值为 dict。"""
        result = {}
        for name, widget in self._widgets.items():
            if isinstance(widget, QComboBox):
                result[name] = (widget.currentData() if name == "test_type" else widget.currentText())
            elif isinstance(widget, MSpinBox):
                result[name] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                result[name] = widget.value()
            elif isinstance(widget, MTimeEdit):
                t = widget.time()
                result[name] = t.toString("mm:ss") if t.isValid() else "00:00"
            elif isinstance(widget, MSwitch):
                result[name] = widget.isChecked()
        return result

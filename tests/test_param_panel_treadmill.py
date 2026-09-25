"""
Tests for ParamPanel treadmill dynamic form rebuild.

Skips the entire module if dayu_widgets / Qt are unavailable.
Import guards are placed before any Qt imports to prevent import-time crashes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Do Qt/dayu import-skip FIRST, before any other Qt imports
import pytest  # noqa: E402

pytest.importorskip("dayu_widgets", reason="dayu_widgets / Qt not available")

# Now it is safe to import Qt classes
from qtpy.QtCore import QTime  # noqa: E402
from qtpy.QtWidgets import QApplication, QComboBox, QDoubleSpinBox  # noqa: E402

from dayu_widgets.spin_box import MSpinBox, MTimeEdit  # noqa: E402

from config.treadmill_config import (  # noqa: E402
    TreadmillGaitConfig,
    TreadmillRunningConfig,
)
from ui.param_panel import ParamPanel  # noqa: E402


def _ensure_app() -> QApplication:
    """Create (or reuse) a QApplication instance for headless tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv if sys.argv else [])
    return app


class TestParamPanelTreadmill:
    """Smoke tests: ParamPanel dynamic rebuild when selecting treadmill mode."""

    _panel: ParamPanel

    def setup_method(self) -> None:
        _ensure_app()
        self._panel = ParamPanel()

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _select_test_type(self, text: str) -> None:
        """Select a test type from the combo box. Replicates UI change flow."""
        combo = self._panel._widgets["test_type"]
        assert isinstance(combo, QComboBox)
        idx = combo.findText(text)
        assert idx >= 0, f"Test type '{text}' not found in combo"
        combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    #  Layer 2: Main treadmill params
    # ------------------------------------------------------------------

    def test_treadmill_gait_has_speed_and_direction(self) -> None:
        self._select_test_type("Treadmill Gait Test")

        assert "treadmill_speed" in self._panel._widgets
        assert "direction" in self._panel._widgets
        assert isinstance(self._panel._widgets["treadmill_speed"], QDoubleSpinBox)
        assert isinstance(self._panel._widgets["direction"], QComboBox)

    def test_treadmill_running_has_speed_and_direction(self) -> None:
        self._select_test_type("Treadmill Running Test")

        assert "treadmill_speed" in self._panel._widgets
        assert "direction" in self._panel._widgets

    # ------------------------------------------------------------------
    #  Layer 3: Filter / gait params
    # ------------------------------------------------------------------

    def test_treadmill_gait_filter_widgets(self) -> None:
        """Treadmill Gait Test shows gait-specific Layer3 widgets."""
        self._select_test_type("Treadmill Gait Test")

        assert "min_step_length" in self._panel._widgets
        assert "filter_gaitr_in" in self._panel._widgets
        assert "filter_gaitr_out" in self._panel._widgets
        assert "automatic_data_filter" in self._panel._widgets

        # Type checks
        assert isinstance(self._panel._widgets["min_step_length"], QDoubleSpinBox)
        assert isinstance(self._panel._widgets["filter_gaitr_in"], MSpinBox)
        assert isinstance(self._panel._widgets["filter_gaitr_out"], MSpinBox)

    def test_treadmill_running_filter_widgets(self) -> None:
        """Treadmill Running Test has gaitr filters but NOT automatic_data_filter."""
        self._select_test_type("Treadmill Running Test")

        assert "filter_gaitr_in" in self._panel._widgets
        assert "filter_gaitr_out" in self._panel._widgets
        assert "automatic_data_filter" not in self._panel._widgets

    # ------------------------------------------------------------------
    #  Jump Test should NOT have treadmill widgets
    # ------------------------------------------------------------------

    def test_jump_test_lacks_treadmill_widgets(self) -> None:
        self._select_test_type("Jump Test")

        assert "treadmill_speed" not in self._panel._widgets
        assert "direction" not in self._panel._widgets
        assert "min_step_length" not in self._panel._widgets
        assert "filter_gaitr_in" not in self._panel._widgets
        assert "filter_gaitr_out" not in self._panel._widgets

    def test_manual_form_exposes_only_supported_modes_and_triggers(self) -> None:
        test_types = self._panel._widgets["test_type"]
        assert [
            test_types.itemText(index) for index in range(test_types.count())
        ] == [
            "Jump Test",
            "Sprint and Gait Test",
            "地面跑步",
            "Treadmill Gait Test",
            "Treadmill Running Test",
        ]
        assert "External impulse" not in [
            self._panel._widgets["start_type"].itemText(index)
            for index in range(self._panel._widgets["start_type"].count())
        ]
        assert not self._panel._optional_section.isVisible()

    def test_manual_form_owns_a_dark_theme_without_global_dayu_theme(self) -> None:
        self._panel.resize(900, 600)
        self._panel.show()
        QApplication.processEvents()

        assert self._panel.objectName() == "ParamPanelRoot"
        assert "#121923" in self._panel.styleSheet()
        assert self._panel.grab().toImage().pixelColor(5, 5).lightness() < 80
        assert all(
            row.objectName() == "ParamFormRow"
            for name, row in self._panel._rows.items()
            if name != "metronome_enabled"
        )

    # ------------------------------------------------------------------
    #  get_config() returns correct type
    # ------------------------------------------------------------------

    def test_get_config_returns_treadmill_gait_config(self) -> None:
        self._select_test_type("Treadmill Gait Test")
        config = self._panel.get_config()
        assert isinstance(config, TreadmillGaitConfig)

    def test_get_config_includes_treadmill_speed(self) -> None:
        self._select_test_type("Treadmill Gait Test")

        speed_widget = self._panel._widgets["treadmill_speed"]
        assert isinstance(speed_widget, QDoubleSpinBox)
        speed_widget.setValue(8.5)

        config = self._panel.get_config()
        assert config.treadmill_speed == 8.5
        assert config.direction == "Opposite side"

    def test_treadmill_gait_defaults_to_walking_speed_and_opposite_direction(self) -> None:
        self._select_test_type("Treadmill Gait Test")

        speed_widget = self._panel._widgets["treadmill_speed"]
        direction_widget = self._panel._widgets["direction"]
        assert isinstance(speed_widget, QDoubleSpinBox)
        assert isinstance(direction_widget, QComboBox)

        config = self._panel.get_config()
        assert speed_widget.value() == 3.0
        assert direction_widget.currentText() == "Opposite side"
        assert config.treadmill_speed == 3.0
        assert config.direction == "Opposite side"

    def test_treadmill_running_defaults_to_running_speed_and_opposite_direction(self) -> None:
        self._select_test_type("Treadmill Running Test")

        speed_widget = self._panel._widgets["treadmill_speed"]
        direction_widget = self._panel._widgets["direction"]
        assert isinstance(speed_widget, QDoubleSpinBox)
        assert isinstance(direction_widget, QComboBox)

        config = self._panel.get_config()
        assert speed_widget.value() == 6.0
        assert direction_widget.currentText() == "Opposite side"
        assert config.treadmill_speed == 6.0
        assert config.direction == "Opposite side"

    def test_get_config_returns_compatible_after_jump_switch(self) -> None:
        """Switching back to Jump Test should return TestConfig."""
        self._select_test_type("Treadmill Gait Test")
        self._select_test_type("Jump Test")

        from config.test_config import TestConfig

        config = self._panel.get_config()
        assert isinstance(config, TestConfig)

    def test_set_config_treadmill_gait_rebuilds_without_dict_runtime_error(self) -> None:
        config = TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="02:30",
            treadmill_speed=6.5,
            direction="Opposite side",
        )

        self._panel.set_config(config)

        assert self._panel._test_type == "Treadmill Gait Test"
        assert "treadmill_speed" in self._panel._widgets
        assert self._panel._widgets["treadmill_speed"].value() == 6.5

    def test_set_config_can_switch_from_treadmill_back_to_jump(self) -> None:
        from config.test_config import TestConfig

        self._panel.set_config(
            TreadmillGaitConfig(
                stop_type="End of Time",
                test_length="02:30",
                treadmill_speed=6.5,
                direction="Opposite side",
            )
        )

        self._panel.set_config(TestConfig(number_of_jumps=7))

        assert self._panel._test_type == "Jump Test"
        assert "treadmill_speed" not in self._panel._widgets
        assert self._panel.get_config().number_of_jumps == 7

    # ------------------------------------------------------------------
    #  Default values
    # ------------------------------------------------------------------

    def test_min_step_length_default(self) -> None:
        """min_step_length has schema default=10.0, matches dataclass."""
        self._select_test_type("Treadmill Gait Test")
        assert self._panel._widgets["min_step_length"].value() == 10.0

    def test_filter_params_default_to_zero(self) -> None:
        self._select_test_type("Treadmill Gait Test")
        assert self._panel._widgets["filter_gaitr_in"].value() == 0
        assert self._panel._widgets["filter_gaitr_out"].value() == 0

    def test_automatic_data_filter_defaults_to_zero(self) -> None:
        """automatic_data_filter default is 0 (disabled), despite range 10-90."""
        self._select_test_type("Treadmill Gait Test")
        assert self._panel._widgets["automatic_data_filter"].value() == 0

    # ------------------------------------------------------------------
    #  Common filters preserved
    # ------------------------------------------------------------------

    def test_treadmill_retains_common_filters(self) -> None:
        self._select_test_type("Treadmill Gait Test")

        assert "min_contact_time" in self._panel._widgets
        assert "min_flight_time" in self._panel._widgets
        assert "max_flight_time" in self._panel._widgets

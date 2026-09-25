import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import unittest

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication

from ui.led_panel import LEDPanel
from ui.led_con_3m import SerialDataWidget


APP = QApplication.instance() or QApplication([])


class DisplayPerformanceTests(unittest.TestCase):
    def test_ui_refresh_timer_targets_smooth_precise_updates(self):
        widget = SerialDataWidget()
        try:
            self.assertLessEqual(widget._ui_timer.interval(), 17)
            self.assertEqual(widget._ui_timer.timerType(), Qt.PreciseTimer)
        finally:
            widget.close()

    def test_rapid_updates_only_store_latest_state_without_widget_churn(self):
        panel = LEDPanel()
        off = [0] * 96
        on = [1] * 96

        started = time.perf_counter()
        for index in range(2000):
            panel.set_leds(on if index % 2 else off)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.05)
        self.assertEqual(panel.led_states(), tuple(on))

    def test_panel_renders_latest_led_state(self):
        panel = LEDPanel(rows=1, cols=2)
        panel.resize(60, 30)
        panel.set_leds([1, 0])
        panel.show()
        APP.processEvents()

        image = panel.grab().toImage()
        left = image.pixelColor(15, 15)
        right = image.pixelColor(45, 15)

        self.assertGreater(left.green(), right.green())
        self.assertGreater(left.green(), left.red())
        panel.close()


if __name__ == "__main__":
    unittest.main()

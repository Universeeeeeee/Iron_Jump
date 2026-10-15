"""Run the same production regression tests against each experimental variant."""
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE)]
from fused_runtime import warmup
from install_variant import install
warmup()
install(sys.argv[1])
import pytest
raise SystemExit(pytest.main(['-q', 'tests/test_beam_quality.py', 'tests/test_active_segments.py',
                             'tests/test_sensor_interface.py', 'tests/test_session_controller_lifecycle.py']))

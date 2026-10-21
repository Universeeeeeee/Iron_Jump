"""Run existing domain tests against one isolated candidate at a time."""
import os
import json
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from qtpy.QtWidgets import QApplication
TEST_APP = QApplication.instance() or QApplication([])

from experiment import HERE, ROOT, processor_class, WalkingProcessor, OvergroundRunningProcessor
from candidates import CancelledRuntime

variant = sys.argv[1]
if variant == 'combined':
    selected=json.loads((HERE/'combined_features.json').read_text())['selected']
    os.environ['IRON_SPARSE_FEATURES']=','.join(selected)
from candidates import enabled
import engine.modes.walking_processor as walking
import engine.modes.overground_running_processor as running
import engine.walking_session as walking_session
import engine.device_quality_session as quality
import hardware.walking_preflight as preflight

if variant in ('idle', 'clusters', 'combined'):
    walking.WalkingProcessor = processor_class(WalkingProcessor, variant)
    running.OvergroundRunningProcessor = processor_class(OvergroundRunningProcessor, variant)
    walking_session.WalkingProcessor = walking.WalkingProcessor
if enabled(variant, 'runtime'):
    quality.RuntimeBeamEvidence = preflight.RuntimeBeamEvidence = CancelledRuntime

assert Path(walking.__file__).is_relative_to(HERE/'baseline')
assert Path(quality.__file__).is_relative_to(HERE/'baseline')

import pytest
tests = ['test_ground_stability_filter.py', 'test_ground_settled_filter.py',
         'test_ground_payload_mirror.py', 'test_walking_contact_fragments.py',
         'test_walking_narrow_candidates.py', 'test_walking_terminal_release.py',
         'test_running_pending_growth.py', 'test_running_contact_competition.py',
         'test_ground_metric_validity.py', 'test_ground_publication_latency.py',
         'test_ground_observation_budget.py', 'test_running_pending_fragments.py',
         'test_walking_temporal_islands.py', 'test_ground_ownership_publication.py']
result = pytest.main(['-q', '--disable-warnings', '--tb=short',
                     '--junitxml='+str(HERE/f'regression_{variant}.xml'),
                     *[str(ROOT/'tests'/x) for x in tests]])
from experiment import CALLBACK_ERRORS, dump
dump(HERE/f'regression_{variant}_callbacks.json', {'unexpected_callback_errors': CALLBACK_ERRORS})
sys.exit(result if result else int(bool(CALLBACK_ERRORS)))

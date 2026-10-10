from copy import deepcopy
import csv

import pytest

from tests.test_ground_session_replay import walking_capture
from tools.audit_walking_evidence import audit_frames, packed, verify_summary


def test_trace_matches_original_bits_and_known_walk(qapp, walking_capture, tmp_path):
    audit = audit_frames(walking_capture, tmp_path / 'frames.csv')
    assert audit['status'] == 'passed'
    assert audit['recomputed_metrics']['valid_steps'] == 2
    assert audit['recomputed_metrics']['valid_cycles'] == 1
    assert audit['recomputed_metrics']['mean_contact_s'] == pytest.approx(.3)
    assert audit['recomputed_metrics']['single_support_s'] == pytest.approx(.6)
    assert audit['recomputed_metrics']['double_support_s'] == 0
    assert audit['origin_sample_time_s'] == 3.4
    assert audit['contact_evidence'][0]['edges']['start']['sample_index'] == 3400
    assert audit['contact_evidence'][0]['edges']['end']['sample_index'] == 3700
    with (tmp_path / 'frames.csv').open() as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 4000
    assert int(rows[0]['source_frame_ordinal_0based']) == 3000
    for row in rows:
        raw = walking_capture[int(row['source_frame_ordinal_0based'])]
        assert row['raw_contact_packed_hex'] == packed(raw.contact_bits)
    # Corrupt a report scalar: the checker must reject it despite coherent contacts.
    summary = deepcopy(audit['replay']['summary'])
    summary['mean_step_m'] += .1
    points = {c['id']: c['position_samples'] for c in audit['contact_evidence']}
    checks, _ = verify_summary(summary, audit['origin_sample_time_s'], points)
    assert [x['name'] for x in checks if not x['passed']] == ['mean_step_m']
    # Corrupt a stored landing position: independent beam centres remain unchanged.
    summary = deepcopy(audit['replay']['summary'])
    summary['contacts'][0]['position_m'] += .1
    checks, _ = verify_summary(summary, audit['origin_sample_time_s'], points)
    assert [x['name'] for x in checks if not x['passed']] == ['contact.0.position_m']


def test_rejected_contact_is_not_skipped_to_invent_step(qapp, walking_capture, tmp_path):
    from dataclasses import replace
    frames = [replace(f, contact_bits=bytes(len(f.contact_bits)))
              if 3880 <= f.sample_index < 4150 else f for f in walking_capture]
    audit = audit_frames(frames, tmp_path / 'frames.csv')
    assert audit['status'] == 'passed'
    assert audit['recomputed_metrics']['valid_steps'] == 0
    assert len(audit['step_decisions']) == 2
    assert all(not x['included'] for x in audit['step_decisions'])
    assert all('contact_1:short_contact' in x['reasons'] for x in audit['step_decisions'])


def test_empty_field_has_no_numeric_measurement(qapp, walking_capture, tmp_path):
    audit = audit_frames(walking_capture[:3300], tmp_path / 'frames.csv')
    assert audit['status'] == 'passed'
    assert audit['recomputed_metrics']['mean_step_m'] is None
    assert audit['recomputed_metrics']['walking_speed_m_s'] is None


def test_unarmed_capture_is_not_a_pass(qapp, walking_capture, tmp_path):
    audit = audit_frames(walking_capture[:1000], tmp_path / 'frames.csv')
    assert audit['status'] == 'not_armed'

"""Reliable landing counts do not manufacture gait relationships."""
from copy import deepcopy
from dataclasses import replace
import pytest
from engine.footfall_records import active_touch_events, footfall_records
from tests.test_overground_walking import processor, walk, CONTACTS


def test_single_landing_unknown_direction_has_one_record_without_relationships():
    p = processor(stop_type='Software command')
    walk(p, [(100, 800, .35)], 900)
    summary = p.summary()
    assert summary['recognized_steps'] == len(summary['footfalls']) == 1
    assert summary['valid_steps'] == len(summary['steps']) == summary['valid_cycles'] == 0
    assert summary['direction'] == 0
    row = summary['footfalls'][0]
    assert row['side'] == 'unknown' and row['side_missing_reason']
    assert row['step_length_m']['value'] is None
    assert row['step_length_m']['missing_reason'] == 'no_valid_step_relationship'
    assert row['raw_landing_position_m'] == summary['landing_positions_m'][str(row['contact_id'])]


def test_duplicate_publication_and_retraction_use_latest_revision():
    p = processor(stop_type='Software command')
    walk(p, CONTACTS, 2400)
    summary = p.summary()
    events = summary['event_publications']
    duplicated = deepcopy(summary)
    duplicated['event_publications'] += deepcopy(events)
    assert len(footfall_records(duplicated)) == summary['recognized_steps']
    event = dict(events[0], active=False, revision=2)
    duplicated['event_publications'] += [event, events[0]]
    records = footfall_records(duplicated)
    assert len(records) == summary['recognized_steps'] - 1
    assert event['contact_id'] not in {row['contact_id'] for row in records}
    assert not any(row['active'] for row in active_touch_events([event]))


def test_metric_ambiguity_keeps_reliable_landing_without_filling_metrics():
    p = processor(stop_type='Software command')
    walk(p, CONTACTS, 2400)
    summary = p.summary()
    row = summary['contacts'][0]
    row['side'] = 'unknown'
    row['contact_s'] = dict(value=None, valid=False, missing_reason='ambiguous_contacts')
    summary['steps'] = []
    records = footfall_records(summary)
    assert len(records) == summary['recognized_steps']
    assert records[0]['contact_s']['missing_reason'] == 'ambiguous_contacts'
    assert all(record['step_length_m']['value'] is None for record in records)


def test_report_roundtrip_and_excel_preserve_separate_landings_and_relationships(tmp_path):
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.excel import build_report_workbook
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput, ReportDataPackage
    p = processor(stop_type='Software command')
    walk(p, CONTACTS, 2400)
    report = p.build_report('manual')
    restored = _report_from_detail(_report_detail(report))
    assert restored.recognized_steps == report.recognized_steps == 4
    assert restored.walking_summary['valid_steps'] == 3
    book = build_report_workbook(restored)
    assert book['Walking footfalls'].max_row == 5
    assert book['Walking steps'].max_row == 4
    package = ReportDataPackageBuilder().build(restored, ReportContextInput(session_id=1, test_type='Sprint and Gait Test'))
    assert package.metadata.schema_version == '1.2'
    assert package.payload.recognized_steps == 4
    records = next(rows.records for rows in package.record_sets if rows.record_type == 'ground_footfall')
    assert len(records) == 4
    assert 'step_length_m' not in records[0].values
    assert package.payload.record_sources[records[0].record_id]['row']['step_length_m']['value'] is None
    assert sum('step_time_s' in row.values for rs in package.record_sets for row in rs.records)==3
    assert ReportDataPackage.model_validate_json(package.model_dump_json()) == package


def test_walking_GUI_counts_active_landings_and_uses_recognition_title(qtbot):
    from ui.views.execution_view import ExecutionView
    from config.walking_config import WalkingConfig
    p = processor(stop_type='Software command')
    walk(p, CONTACTS, 2400)
    summary = p.summary()
    view = ExecutionView();qtbot.addWidget(view);view.configure(WalkingConfig())
    view._camera_start_timer.stop()
    def show(value):
        view.on_gait_snapshot(dict(walking=value,touch_count=value['recognized_steps'],status='行走中',stride_count=0,velocity_count=0))
    show(summary)
    assert view._card_steps._title.text() == '识别步数'
    assert view._card_steps._value.text() == '4'
    withdrawn = deepcopy(summary);withdrawn['event_publications'][0].update(active=False,revision=2)
    withdrawn['footfalls'] = footfall_records(withdrawn);withdrawn['recognized_steps'] = len(withdrawn['footfalls'])
    show(withdrawn)
    assert view._card_steps._value.text() == '3'


@pytest.mark.parametrize('field,value',[('recognized_steps',99),('raw_landing_position_m',999.),('touch_sample',-1)])
def test_report_package_rejects_inconsistent_footfall_contract(field,value):
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    p=processor(stop_type='Software command');walk(p,CONTACTS,2400);report=p.build_report('manual')
    if field=='recognized_steps':report.walking_summary[field]=value
    else:report.walking_summary['footfalls'][0][field]=value
    with pytest.raises(ValueError):
        ReportDataPackageBuilder().build(report,ReportContextInput(session_id=1,test_type='Sprint and Gait Test'))

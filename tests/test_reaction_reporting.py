"""Reaction snapshots retain unsuccessful attempts and uncalibrated clock evidence."""
from dataclasses import replace
from io import BytesIO

from openpyxl import load_workbook
import pytest

from config.reaction_config import ReactionConfig
from config.reaction_report import ReactionTestReport, ReactionTrialRecord
from data.subject_store import SubjectStore
from engine.reaction_session import ReactionSession
from hardware.sensor_frame import DeviceLayout, SensorFrame
from reporting.excel import REACTION_LABELS, REACTION_TIMING_NOTE, build_report_workbook, has_export_data
from reporting.pdf import report_html


@pytest.fixture
def processed_report():
    config = ReactionConfig(number_of_repetitions=1, ready_hold_ms=3, confirmation_ms=3,
                            stimulus_delay_min_ms=20, stimulus_delay_max_ms=20)
    session = ReactionSession(config, clock=lambda: 0)
    session.begin(0)

    def feed(sample, host_ms, occupied):
        session.on_frame(SensorFrame(
            stream_id="fixture-stream", layout=DeviceLayout.linear(1), frame_index=sample,
            sample_index=sample, received_monotonic_ns=host_ms * 1_000_000,
            contact_bits=bytes([int(occupied)] + [0] * 95), valid_bits=b"\x01" * 96,
            wire_payload=b"\xff" * 12))

    for sample in range(4):
        feed(sample, sample, True)
    session.poll(23_000_000)
    session.acknowledge_stimulus(1, 23_000_000, "visual", host_ns=23_000_000)
    for sample in range(4, 8):
        feed(sample, 155, False)
    return config, session.build_report()


@pytest.fixture
def all_attempts_report():
    request = 1_234_567_890_123_456
    first = ReactionTrialRecord(
        1, "visual", "takeoff", "valid", request, request + 80_000_000,
        2**32 + 15, 15, 80.0, stream_id="fixture-stream",
        stimulus_scheduled_host_ns=request - 1_000_000,
        confirmation_sample_index=2**32 + 18, confirmation_received_host_ns=request + 81_000_000)
    trials = [first, replace(first, index=2, reaction_time_ms=120.0,
                             response_received_host_ns=request + 120_000_000),
              replace(first, index=3, modality="acoustic", reaction_time_ms=250.0,
                      response_received_host_ns=request + 250_000_000)]
    for index, status in enumerate(("early", "timeout", "gap", "cancelled", "stimulus_failed"), 4):
        trials.append(ReactionTrialRecord(index, "acoustic", "takeoff", status,
                                          quality_flags=(status + "_evidence",)))
    return ReactionTestReport(tuple(trials), "cancelled", ReactionConfig().to_dict())


def test_processed_report_roundtrips_sqlite_and_summary_history(tmp_path, processed_report):
    config, report = processed_report
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    subject_id = store.create_subject("反应时测试", 2000)
    session_id = store.record_session(subject_id, config, report)
    saved = store.get_session(session_id)
    assert saved.report == report
    assert saved.config == config
    assert saved.finish_reason == "completed"
    assert saved.report.trials[0].reaction_time_ms == 132.0
    assert saved.report.trials[0].response_sample_index == 4
    assert saved.report.trials[0].confirmation_sample_index == 7
    assert saved.report_summary["median_reaction_time_ms"] == 132.0
    assert saved.report_summary["grouped_statistics"]["visual"]["mean_ms"] == 132.0
    assert saved.report_summary["grouped_statistics"]["acoustic"]["mean_ms"] is None
    assert "trials" not in saved.report_summary
    assert "export_frames" not in saved.report_detail
    listing = store.get_sessions(subject_id, include_detail=False)[0]
    assert listing.finish_reason == "completed" and listing.has_report
    assert store.get_recent_history(subject_id)[0]["min_contact_time"] is None


def test_every_attempt_and_raw_clock_survive_sqlite_and_artifacts(tmp_path, all_attempts_report):
    from ui.measurement_process.artifacts import load_report, save_report

    store = SubjectStore(tmp_path / "subjects.sqlite3")
    session_id = store.record_session(None, ReactionConfig(), all_attempts_report)
    saved = store.get_session(session_id)
    assert saved.report == all_attempts_report
    assert saved.finish_reason == "cancelled"
    assert saved.report_summary["attempt_count"] == 8
    assert saved.report_summary["valid_count"] == 3
    assert saved.report_summary["timing_quality"] == "uncalibrated"
    assert load_report(tmp_path, save_report(tmp_path, saved.report)) == saved.report


def test_excel_reopens_with_numeric_results_and_exact_raw_clocks(all_attempts_report):
    assert has_export_data(all_attempts_report)
    book = build_report_workbook(all_attempts_report)
    stream = BytesIO()
    book.save(stream)
    book.close()
    stream.seek(0)
    restored = load_workbook(stream)
    assert restored.sheetnames == ["Reaction Summary", "Reaction Groups", "Reaction Trials", "Reaction Config"]
    groups = list(restored["Reaction Groups"].values)
    assert groups[1] == ("visual", "takeoff", 2, 100, 100, 80, 120, 20)
    assert groups[2] == ("acoustic", "takeoff", 1, 250, 250, 250, 250, 0)
    rows = list(restored["Reaction Trials"].values)
    records = [dict(zip(rows[0], row)) for row in rows[1:]]
    assert len(records) == len(all_attempts_report.trials)
    for record, trial in zip(records, all_attempts_report.trials):
        assert record["status"] == trial.status
        assert record["reaction_time_ms"] == trial.reaction_time_ms
        assert record["is_included_in_statistics"] == (trial.status == "valid")
        assert record["response_sample_index"] == trial.response_sample_index
        assert record["actual_stimulus_onset_ns"] is None
        assert record["timing_quality"] == "uncalibrated"
    assert records[0]["stimulus_request_host_ns"] == "1234567890123456"
    assert records[0]["response_received_host_ns"] == "1234567970123456"
    assert records[0]["stimulus_scheduled_host_ns"] == "1234567889123456"
    assert records[0]["confirmation_received_host_ns"] == "1234567971123456"
    assert records[0]["confirmation_sample_index"] == 2**32 + 18
    assert records[-1]["quality_flags"] == '["stimulus_failed_evidence"]'
    restored.close()


def test_no_valid_result_remains_unavailable_in_exports(all_attempts_report):
    report = replace(all_attempts_report, trials=all_attempts_report.trials[3:])
    assert has_export_data(report)
    assert not has_export_data(ReactionTestReport())
    book = build_report_workbook(report)
    for row in list(book["Reaction Groups"].values)[1:]:
        assert row[2] == 0 and row[3:] == (None, None, None, None, None)
    text = report_html(report, title="反应时", stats=[], reason="已取消")
    assert "未测得" in text
    assert "0.000" not in text
    book.close()


@pytest.mark.parametrize("detailed", [False, True])
def test_pdf_retains_all_attempts_and_timing_qualification(all_attempts_report, detailed):
    text = report_html(all_attempts_report, title="反应时", stats=[], reason="已取消", detailed=detailed)
    assert REACTION_TIMING_NOTE in text
    assert "按刺激类型和动作分组" in text
    assert "100.000" in text and "250.000" in text
    for status in {trial.status for trial in all_attempts_report.trials}:
        assert REACTION_LABELS[status] in text
    assert "1 ms" not in text
    if detailed:
        assert "1234567890123456" in text
        assert str(2**32 + 15) in text


def test_native_pdf_writer_smoke(qapp, tmp_path, all_attempts_report):
    from ui.report_pdf import write_report_pdf

    path = tmp_path / "reaction.pdf"
    write_report_pdf(path, all_attempts_report, title="反应时", stats=[], reason="已取消", detailed=True)
    assert path.read_bytes().startswith(b"%PDF-")
    assert path.stat().st_size > 1000

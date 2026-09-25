from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from data.subject_store import SubjectStore
from hardware.rc200u import (
    STATUS_NO_CARD, Rc200uReader, Rc200uUnavailable, SimulatedRc200u,
    UidRead, format_uid, open_reader,
)
from tools.rc200u_probe import Rc200uProbeWindow


def test_format_uid_preserves_sdk_bytes():
    assert format_uid(bytes.fromhex("AABBCCDD000000")) == "AABBCCDD000000"
    assert format_uid(bytes.fromhex("04112233445566")) == "04112233445566"
    assert format_uid(bytes.fromhex("00000000")) is None


def test_open_reader_requires_explicit_simulation_off_windows(monkeypatch):
    monkeypatch.setattr("hardware.rc200u.sys.platform", "darwin")
    with pytest.raises(Rc200uUnavailable, match="Windows-only"):
        open_reader()
    reader = open_reader(simulate=True)
    assert reader.backend == "simulated"
    assert reader.request_uid().status == STATUS_NO_CARD


def test_simulated_reader_emits_queued_uid():
    reader = SimulatedRc200u()
    reader.queue_uid("aa-bb-cc-dd-00-00-00")
    result = reader.request_uid()
    assert result.ok
    assert result.uid == "AABBCCDD000000"
    reader.clear()
    assert reader.request_uid().uid is None


def test_probe_binds_uid_to_existing_subject(qtbot, tmp_path: Path):
    store = SubjectStore(tmp_path / "iron_jump.sqlite3")
    alice_id = store.create_subject("Alice", 1990)
    reader = SimulatedRc200u()
    window = Rc200uProbeWindow(reader, store)
    qtbot.addWidget(window)
    reader.queue_uid("AABBCCDD")
    window.poll_once()
    assert window._uid_label.text() == "AABBCCDD"
    assert "未绑定" in window._match_label.text()
    window._select_subject(alice_id)
    window._bind_selected()
    assert store.get_subject_by_card_uid("AABBCCDD").id == alice_id
    assert "Alice" in window._match_label.text()
    reader.clear()
    window.poll_once()
    reader.queue_uid("AABBCCDD")
    window.poll_once()
    assert "Alice" in window._match_label.text()


def test_reader_converts_beep_milliseconds_to_sdk_ticks(monkeypatch):
    lib = SimpleNamespace(piccrequest=Mock(), pcdbeep=Mock())
    monkeypatch.setattr(Rc200uReader, "_load_dll", Mock(return_value=lib))
    reader = Rc200uReader()
    reader.beep(40)
    lib.pcdbeep.assert_called_once_with(20)


@pytest.mark.parametrize("status, expected", [(0, "04112233000000"), (8, None), (23, None), (1, None)])
def test_reader_obeys_ul_status_and_preserves_uid(monkeypatch, status, expected):
    def request(buf):
        buf[:] = bytes.fromhex("04112233000000")
        return status

    lib = SimpleNamespace(piccrequest_ul=Mock(side_effect=request))
    monkeypatch.setattr(Rc200uReader, "_load_dll", Mock(return_value=lib))
    assert Rc200uReader().request_uid().uid == expected


def test_reader_supports_legacy_four_byte_api(monkeypatch):
    def request(buf):
        buf[:] = bytes.fromhex("AABBCCDD")
        return 10

    lib = SimpleNamespace(piccrequest=Mock(side_effect=request))
    monkeypatch.setattr(Rc200uReader, "_load_dll", Mock(return_value=lib))
    assert Rc200uReader().request_uid().uid == "AABBCCDD"


@pytest.mark.parametrize("classic_status", [0, 10, 8, 9, 23])
def test_f08_falls_back_when_ul_cannot_read_serial(monkeypatch, classic_status):
    def classic(buf):
        buf[:] = bytes.fromhex("139D013A")
        return classic_status

    lib = SimpleNamespace(
        piccrequest_ul=Mock(return_value=9),
        piccrequest=Mock(side_effect=classic),
    )
    monkeypatch.setattr(Rc200uReader, "_load_dll", Mock(return_value=lib))
    result = Rc200uReader().request_uid()
    lib.piccrequest.assert_called_once()
    if classic_status in (0, 10):
        assert result.uid == "139D013A"
        assert result.status == classic_status
    else:
        assert result.uid is None
        assert result.status == 9


@pytest.mark.parametrize("ul_status", [0, 8, 23])
def test_reader_does_not_retry_success_or_unrelated_ul_errors(monkeypatch, ul_status):
    def request(buf):
        buf[:] = bytes.fromhex("04112233000000")
        return ul_status

    lib = SimpleNamespace(piccrequest_ul=Mock(side_effect=request), piccrequest=Mock())
    monkeypatch.setattr(Rc200uReader, "_load_dll", Mock(return_value=lib))
    result = Rc200uReader().request_uid()
    assert result.uid == ("04112233000000" if ul_status == 0 else None)
    lib.piccrequest.assert_not_called()


def test_reader_rejects_dll_without_uid_api(monkeypatch):
    monkeypatch.setattr(Rc200uReader, "_load_dll", Mock(return_value=SimpleNamespace()))
    with pytest.raises(Rc200uUnavailable, match="piccrequest"):
        Rc200uReader()


def test_probe_shows_error_changes_without_card(qtbot, tmp_path):
    reader = SimulatedRc200u()
    reader.request_uid = Mock(return_value=UidRead(None, 23, "driver missing"))
    window = Rc200uProbeWindow(reader, SubjectStore(tmp_path / "probe.sqlite3"))
    qtbot.addWidget(window)
    window.poll_once()
    assert "23" in window._uid_label.text()
    reader.request_uid.return_value = UidRead(None, 24, "timeout")
    window.poll_once()
    assert "24" in window._uid_label.text()
    assert "status=24" in window._log_view.toPlainText()
    reader.request_uid.return_value = UidRead(None, STATUS_NO_CARD, "no card")
    window.poll_once()
    assert window._uid_label.text() == "等待贴卡"

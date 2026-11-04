import time
from dataclasses import replace
from hardware.known_beams import known_bad_indices
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import WalkingPreflight
from hardware.beam_quality import BeamQualityPolicy, masked_frame


def test_registered_beam_stays_unavailable_when_raw_bit_is_clear():
    layout=DeviceLayout.linear(8);gate=WalkingPreflight(BeamQualityPolicy(observation_seconds=1),known_bad_beams=('7:1',))
    assert known_bad_indices(layout,('7:1',))==(576,)
    assert known_bad_indices(DeviceLayout.linear(),('7:1',))==()
    for n in range(1000):
        raw=SensorFrame('test',layout,n,n,time.perf_counter_ns(),bytes(768),bytes([1])*768,bytes([255])*96)
        gate.feed(raw)
    assert gate.context.bad_indices==(576,)
    assert gate.context.bad_types==('已登记坏束',)
    assert gate.context.layout.positions_m==layout.positions_m
    bits=bytearray(768);bits[576]=bits[580]=1
    source=replace(raw,contact_bits=bytes(bits));masked=masked_frame(source,gate.context.bad_indices)
    assert source.contact_bits[576]==1 and masked.contact_bits[576]==0 and masked.contact_bits[580]==1


def test_setup_separates_registered_beam_without_suppressing_new_fault(qtbot,monkeypatch):
    import hardware.known_beams as known
    from ui.views.setup_view import SetupView
    monkeypatch.setattr(known,'load_known_beams',lambda:('7:1',))
    view=SetupView();qtbot.addWidget(view);view.on_device_state('connected');view.on_device_layout(DeviceLayout.linear(8))
    result=dict(status='warning',sample_count=64,disconnected_leds=[577],flickering_leds=[])
    view.on_led_health(result)
    assert 'LED异常' not in view._device_state_label.text()
    assert '已登记坏束' in view._device_meta_label.text() and '第 7 段：1' in view._device_meta_label.text()
    assert view._led_health_result['disconnected_leds']==[577]
    view.on_led_health(dict(result,disconnected_leds=[577,578]))
    assert 'LED异常' in view._device_state_label.text()
    assert '未联通/持续遮挡 LED：第 7 段：2' in view._device_meta_label.text()

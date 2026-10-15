"""A durable touch must reach the visual snapshot without another 100 ms wait."""
from dataclasses import replace

import pytest

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from engine.overground_session import OvergroundSession
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice


def same_pixels(left,right):
    # Two source-over stages can round an 8-bit antialiased edge by at most two levels.
    import numpy as np
    from qtpy.QtGui import QImage
    images=[im.convertToFormat(QImage.Format_RGBA8888) for im in (left,right)]
    assert images[0].size()==images[1].size()
    arrays=[np.frombuffer(im.bits(),dtype=np.uint8).astype(int) for im in images]
    assert np.max(np.abs(arrays[0]-arrays[1]))<=2


@pytest.mark.parametrize('mode', ['walk','run'])
def test_published_touch_emits_a_current_confirmed_visual_in_same_input_turn(qapp, mode):
    layout=DeviceLayout.linear(8)
    config=(WalkingConfig if mode=='walk' else OvergroundRunningConfig)(stop_type='Software command')
    factory=WalkingProcessor if mode=='walk' else OvergroundRunningProcessor
    session=OvergroundSession(config,factory)
    session.start_prepared(PreparedDevice(layout,'latency',-1,0,3000))
    visuals=[];session.visual.connect(visuals.append)
    first_publication=None
    for n in range(250):
        bits=bytearray(768)
        if 100<=n<220:bits[40:61]=b'\x01'*21
        frame=SensorFrame('latency',layout,n,n,10**12+n*1000000,bytes(bits),b'\x01'*768,b'')
        before=session.processor.reliable_touch_count
        count=len(visuals)
        session.on_frame(frame)
        if before==0 and session.processor.reliable_touch_count==1:
            first_publication=n
            assert len(visuals)>count
            assert any(f['status']=='confirmed' for f in visuals[-1]['feet'])
            assert session.processor.touch_events[0]['touch_sample']==100
            break
    assert first_publication is not None


def test_tint_cache_matches_the_uncached_raster_and_survives_state_changes(qtbot):
    import importlib.util
    from pathlib import Path
    from ui.footprint_channel import FootprintChannelWidget
    path=Path(__file__).parents[1]/'exports/ground_boundary_latency_20261014/before_latency/footprint_channel.py'
    spec=importlib.util.spec_from_file_location('uncached_footprint',path)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    cached=FootprintChannelWidget();uncached=original.FootprintChannelWidget()
    for widget in (cached,uncached):
        qtbot.addWidget(widget);widget.resize(300,700);widget.show()
    for side,known,length in [('left',True,20),('right',True,32),('unknown',False,None),('left',True,28)]:
        state={'positions_m':DeviceLayout.linear(8).positions_m,'contact_bits':[0]*768,'valid_bits':[1]*768,
               'feet':[{'status':'confirmed','centroid_cm':52,'length_cm':length,'side':side,'shape_valid':known}]}
        for widget in (cached,uncached):widget.render_state(state)
        same_pixels(cached.grab().toImage(),uncached.grab().toImage())
        previous=dict(cached._tinted_feet)
        same_pixels(cached.grab().toImage(),uncached.grab().toImage())
        assert cached._tinted_feet==previous
    assert len(cached._tinted_feet)==3  # Shape/size changes do not re-tint an unchanged color.


def test_beam_layer_invalidation_and_dynamic_feet_match_uncached_pixels(qtbot):
    import importlib.util
    from pathlib import Path
    from ui.footprint_channel import FootprintChannelWidget
    path=Path(__file__).parents[1]/'exports/ground_boundary_latency_20261014/before_latency/footprint_channel.py'
    spec=importlib.util.spec_from_file_location('uncached_beams',path)
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    cached=FootprintChannelWidget();uncached=original.FootprintChannelWidget()
    for widget in (cached,uncached):
        qtbot.addWidget(widget);widget.resize(300,700);widget.setProperty('integrated',True);widget.show()
    state={'positions_m':list(DeviceLayout.linear(8).positions_m),'contact_bits':[0]*768,'valid_bits':[1]*768,'feet':[]}
    def equal():
        for widget in (cached,uncached):widget.render_state(state)
        same_pixels(cached.grab().toImage(),uncached.grab().toImage())
    equal();initial=cached._beam_layer
    state['feet']=[{'status':'confirmed','centroid_cm':150,'length_cm':28,'side':'left'}]
    equal();assert cached._beam_layer is initial
    state['contact_bits'][140:160]=[1]*20
    equal();assert cached._beam_layer is not initial
    previous=cached._beam_layer;state['valid_bits'][150]=0
    equal();assert cached._beam_layer is not previous
    previous=cached._beam_layer
    for widget in (cached,uncached):widget.set_direction('Opposite side')
    equal();assert cached._beam_layer is not previous
    for widget in (cached,uncached):widget.resize(340,600)
    equal()
    state['positions_m']=[p*1.01 for p in state['positions_m']]
    equal()

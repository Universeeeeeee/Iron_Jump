"""Additional spatial, time-boundary and swallowed-Qt-error rejection checks."""
from dataclasses import replace
import json
import sys
import traceback

from experiment import *
from candidates import idle_eligible


def main():
    rows = []
    for modules in (1, 3, 8):
        for custom in (False, True):
            layout, frames = synthetic('edges', 2100, modules, custom)
            for mode, cls in (('walk', WalkingProcessor), ('run', OvergroundRunningProcessor)):
                dev = PreparedDevice(layout, 'synthetic', -1, 0, 3000)
                p = cls(config_for(mode), dev)
                spatial = SegmentClusters(p)
                original = p._clusters if mode == 'walk' else p._groups
                for f in frames:
                    assert spatial(f.contact_bits) == original(f.contact_bits), (modules, custom, mode, f.sample_index)
                rows.append({'case': 'spatial_custom_geometry', 'modules': modules,
                             'custom': custom, 'mode': mode, 'frames': len(frames), 'exact': True})
    for mode, cls in (('walk', WalkingProcessor), ('run', OvergroundRunningProcessor)):
        layout = DeviceLayout.linear(3)
        for scenario in ('exit', 'gap', 'invalid', 'masked', 'plateau'):
            config = config_for(mode, auto=True)
            dev = PreparedDevice(layout, 'synthetic', -1, 0, 3000)
            a, b = cls(config, dev), processor_class(cls, 'idle')(config, dev)
            hits = 0
            for n in range(1900):
                groups = ([(25, 45)] if 100 <= n < 300 else [(125, 145)] if 400 <= n < 600
                          else [(265, 287)] if 700 <= n < 950 else [])
                if scenario == 'plateau' and 100 <= n < 1700:
                    groups = [(25, 45)]
                f = make_frame(layout, n, groups)
                if scenario == 'gap' and n == 1200:
                    f = replace(f, sample_index=n+2, dropped_frames_before=2, quality_flags=('frame_gap',))
                if scenario == 'invalid' and n == 1200:
                    f = replace(f, valid_bits=bytes(layout.bit_count))
                masked = scenario == 'masked' and n == 1200
                a.process(f, masked_contact=masked); b.process(f, masked_contact=masked)
                assert_equal(state(a), state(b), (mode, scenario, n))
            assert_equal(a.summary(), b.summary(), (mode, scenario, 'summary'))
            rows.append({'case': scenario, 'mode': mode, 'frames': 1900, 'exact': True,
                         'idle_hits': b._exp_idle_hits, 'finished_reason': a.finished_reason})
    # Verify the harness rejects callback errors rather than reporting false equivalence.
    layout, frames = synthetic('empty', 1)
    q, s = pipeline('run', layout, frames, 'baseline')
    def broken(*args):
        raise RuntimeError('injected callback failure')
    q.frame_ready.connect(broken, Qt.DirectConnection)
    try:
        feed_quality(q, frames[0])
        raise AssertionError('callback failure was swallowed')
    except RuntimeError as error:
        assert 'injected callback failure' in str(error)
    CALLBACK_ERRORS.clear()
    rows.append({'case': 'injected_qt_callback_failure', 'rejected': True})
    dump(HERE/'edge_checks.json', {'results': rows, 'all_exact': True})
    print(json.dumps({'cases': len(rows), 'all_exact': True}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(1)

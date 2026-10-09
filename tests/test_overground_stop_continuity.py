"""Stops must retain only the reliable prefix before a local observation loss."""
import pytest

from tests.test_ground_local_observation import processor, replay, sample


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('loss_start', [2099, 2100, 2300])
def test_local_loss_preserves_only_confirmed_stop_prefix(mode, loss_start):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 2400 else [],
                     [0] if loss_start <= n < loss_start + 20 else [])
              for n in range(2500)]
    replay(p, frames)
    stops = p.summary()['stops']
    if loss_start < 2100:
        assert stops == []
    else:
        assert len(stops) == 1
        assert stops[0]['start_s'] == pytest.approx(0)
        assert stops[0]['end_s'] == pytest.approx((loss_start - 100) / 1000)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_repeated_local_loss_does_not_duplicate_or_extend_stop(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 2500 else [],
                     [0] if 2300 <= n < 2320 or 2400 <= n < 2420 else [])
              for n in range(2600)]
    replay(p, frames)
    first = p.summary()['stops']
    p.break_continuity('disconnected')
    assert len(first) == 1
    assert first[0]['end_s'] == pytest.approx(2.2)
    assert p.summary()['stops'] == first


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_stop_survives_release_candidate_timeout(mode):
    p = processor(mode)
    frames = [sample(n, [(.2, .38)] if 100 <= n < 2300 else [],
                     [0] if n >= 2300 and (n - 2300) % 10 != 9 else [])
              for n in range(2400)]
    replay(p, frames)
    assert p.summary()['stops'] == [{'start_s': 0, 'end_s': pytest.approx(2.2)}]


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_local_stop_loss_does_not_block_later_independent_steps(mode):
    p = processor(mode)
    contacts = [(100, 2400, .2, .38), (2600, 2800, .8, .98),
                (2900, 3100, 1.4, 1.58), (3200, 3400, 2., 2.18)]
    frames = [sample(n, [(lo, hi) for start, end, lo, hi in contacts if start <= n < end],
                     [0] if 2300 <= n < 2320 else []) for n in range(3500)]
    replay(p, frames)
    summary = p.summary()
    assert summary['stops'] == [{'start_s': 0, 'end_s': pytest.approx(2.2)}]
    later_steps = [s for s in summary['steps'] if s['from_id'] >= 2]
    assert len(later_steps) == 2
    for step in later_steps:
        if mode == 'walk':
            assert step['time_s'] == pytest.approx(.3)
        else:
            assert step['time_s']['valid']
            assert step['time_s']['value'] == pytest.approx(.3)

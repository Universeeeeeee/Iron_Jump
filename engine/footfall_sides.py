"""Anatomical side follows published footfalls, independently of shape quality."""
from config.footfall_events import active_touch_events


SIDE_POLICY = 'configured_start_active_events_v1'
CAPTURE_BREAKS = {'frame_gap', 'invalid_sample', 'data_timeout', 'disconnected',
                  'device_changed', 'layout_mismatch', 'counter_reset', 'out_of_order_or_reset'}


def event_sides(events, starting_foot, issues):
    """Revisions/withdrawals change event order; optical fragments do not count.

Issues use the processors' absolute device clock, before report normalization.
The first actual acquisition break ends the externally supplied side anchor.
"""
    first = {'Left': 'left', 'Right': 'right'}.get(starting_foot)
    cutoffs = []
    for issue in issues:
        if issue['code'] not in CAPTURE_BREAKS:
            continue
        sample = issue.get('sample')
        if sample is None and issue.get('time_s') is not None:
            sample = round(issue['time_s'] * 1000)
        cutoffs.append(sample if sample is not None else -1)
    cutoff = min(cutoffs) if cutoffs else float('inf')
    return {event['contact_id']: ('unknown' if first is None or event['touch_sample'] > cutoff
            else first if index % 2 == 0 else 'right' if first == 'left' else 'left')
            for index, event in enumerate(active_touch_events(events))}

"""Explain ground contact exclusions without changing measurement validity."""
from collections import Counter
from html import escape


def merged_interval_duration_ms(intervals):
    total = 0
    end = None
    for left, right in sorted((row['start_sample'], row['end_sample']) for row in intervals):
        start = left if end is None else max(left, end)
        total += max(0, right - start)
        end = right if end is None else max(end, right)
    return total


def contact_reason(row, snapshot):
    from reporting.overground_running import REASONS
    code = row.get('exclusion')
    if not code:
        for key in ('touch_s', 'contact_s', 'lift_s'):
            value = row.get(key)
            if isinstance(value, dict) and not value.get('valid'):
                code = value.get('missing_reason')
                if code:
                    break
    if code == 'short_contact':
        minimum = snapshot.get('min_contact_time')
        start, end = row.get('start'), row.get('end')
        if minimum is not None and start is not None and end is not None:
            duration_ms = (end - start) * 1000
            if duration_ms + 1e-6 < minimum:
                return f'接触过短（{duration_ms:.1f} ms < {minimum} ms）'
            if row.get('peak_width_m', .08) < .08:
                return '足迹宽度不足（未达到 8 cm 确认条件）'
            confirmation = snapshot.get('confirmation_ms')
            if confirmation is not None and row.get('observed_samples', confirmation) < confirmation:
                return '有效观测样本不足'
        return '接触未确认（时长或有效观测不足）'
    return REASONS.get(code, code or '')


def contact_quality_html(report):
    summary = getattr(report, 'walking_summary', None) or getattr(report, 'running_summary', None)
    if not summary:
        return ''
    snapshot = report.report_config_snapshot
    counts = Counter(filter(None, (contact_reason(r, snapshot) for r in summary.get('contacts', [])
        if r.get('candidate_outcome') not in {'excluded_nonstep', 'associated_fragment'}
        and not all(r.get(key, {}).get('valid') for key in ('touch_s', 'lift_s', 'contact_s')))))
    content = '<h3>数据质量说明</h3><p>候选接触包含尚未确认为一步的遮挡片段；候选记录数不等于实际步数。同一片段可能导致多个指标缺失。</p>'
    threshold = snapshot.get('min_contact_time')
    confirmation = snapshot.get('confirmation_ms')
    if threshold is not None:
        content += f'<p>本次最短接触时间：{escape(str(threshold))} ms'
        if confirmation is not None:
            content += f'；确认所需有效观测：{escape(str(confirmation))} 个 1 ms 样本'
        content += '。短片段、遮挡归属不明及边界缺失须分别核查，降低阈值不一定增加有效步数。</p>'
    if counts:
        content += '<p>' + '<br>'.join(f'{escape(reason)}：{count} 条接触记录' for reason, count in counts.items()) + '</p>'
    return content

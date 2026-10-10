"""Trace an offline walking report to unmodified source frames; no device access.

Run with --accept-degraded only to acknowledge bad beams in the recording.
The audit checks software arithmetic/provenance, not physical accuracy or L/R truth.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import html
import json
from pathlib import Path
from statistics import mean, median
from unittest.mock import patch

import numpy as np
from qtpy.QtCore import QCoreApplication

from engine.modes.walking_processor import WalkingProcessor
from tools.replay_ground_session import replay_session
from tools.validate_ground_observation import load_capture


def packed(bits):
    return np.packbits(np.frombuffer(bits, dtype=np.uint8), bitorder='little').tobytes().hex()


def verify_summary(summary, origin, position_samples):
    """Recompute distances from beam coordinates and support on a 1 ms lattice.

    Contact association/eligibility remain algorithm outputs, explicitly exposed
    for review. Arithmetic is recomputed without calling processor.summary().
    """
    checks, metrics = [], {}

    def check(name, actual, expected):
        equal = (actual is expected if actual is None or expected is None else
                 bool(np.allclose(actual, expected, atol=1e-8, rtol=1e-8)))
        checks.append({'name': name, 'passed': equal, 'reported': actual, 'recomputed': expected})

    contacts = {c['id']: c for c in summary['contacts']}
    positions = {}
    for cid, c in contacts.items():
        samples = position_samples[cid]
        positions[cid] = median(x['beam_centre_m'] for x in samples)
        check(f'contact.{cid}.position_m', c['position_m'], positions[cid])
        for i, point in enumerate(samples):
            check(f'contact.{cid}.position_sample.{i}', point['stored_m'], point['beam_centre_m'])
    lengths, times = [], []
    for i, step in enumerate(summary['steps']):
        a, b = contacts[step['from_id']], contacts[step['to_id']]
        length = abs(positions[b['id']] - positions[a['id']])
        duration = b['start'] - a['start']
        lengths.append(length)
        times.append(duration)
        check(f'step.{i}.length_m', step['length_m'], length)
        check(f'step.{i}.time_s', step['time_s'], duration)
        check(f'step.{i}.speed_m_s', step['speed_m_s'], length / duration)
    strides, singles, doubles = [], [], []
    for i, cycle in enumerate(summary['cycles']):
        start, end = cycle['start_s'], cycle['end_s']
        first = next(c for c in contacts.values() if abs(c['start'] - start) < 1e-8
                     and c['label'] == cycle['foot'] and c['epoch'] == cycle['epoch'])
        last = next(c for c in contacts.values() if abs(c['start'] - end) < 1e-8
                    and c['label'] == cycle['foot'] and c['epoch'] == cycle['epoch'])
        # Independent discrete integration, instead of production interval splitting.
        samples = np.arange(round((start + origin) * 1000), round((end + origin) * 1000))
        occupancy = np.zeros(len(samples), dtype=int)
        for c in contacts.values():
            if c['confirmed'] and c['end'] is not None:
                occupancy += ((samples >= round((c['start'] + origin) * 1000)) &
                              (samples < round((c['end'] + origin) * 1000)))
        singles.append(float(np.count_nonzero(occupancy == 1) / 1000))
        doubles.append(float(np.count_nonzero(occupancy == 2) / 1000))
        strides.append(abs(positions[last['id']] - positions[first['id']]))
        check(f'cycle.{i}.duration_s', cycle['duration_s'], len(samples) / 1000)
        check(f'cycle.{i}.single_support_s', cycle['single_support_s'], singles[-1])
        check(f'cycle.{i}.double_support_s', cycle['double_support_s'], doubles[-1])
    avg = lambda values: mean(values) if values else None
    contact_times = [c['end'] - c['start'] for c in contacts.values()
                     if c['confirmed'] and c.get('touch_known', bool(c['label'])) and c['end'] is not None
                     and c['exclusion'] in {None, 'pending_touch_order'}
                     and not any(c['start'] < s['end_s'] and c['end'] > s['start_s']
                                 for s in summary['stops'])]
    metrics.update(valid_steps=len(lengths), valid_cycles=len(strides),
                   mean_step_m=avg(lengths), mean_stride_m=avg(strides),
                   mean_contact_s=avg(contact_times), single_support_s=avg(singles),
                   double_support_s=avg(doubles),
                   cadence_per_min=60 * len(times) / sum(times) if times else None,
                   walking_speed_m_s=sum(lengths) / sum(times) if times else None)
    for name, value in metrics.items():
        check(name, summary[name], value)
    for i, value in enumerate(strides):
        check(f'stride.{i}.length_m', summary['stride_lengths_m'][i], value)
    return checks, metrics


def step_decisions(summary):
    """Explain every adjacent candidate pair, including rejected barriers."""
    rows = []
    contacts = [c for c in summary['contacts'] if c.get('candidate_outcome') not in {'excluded_nonstep', 'associated_fragment'}]
    for a, b in zip(contacts, contacts[1:]):
        reasons = []
        for c in (a, b):
            if not c['confirmed'] or not c['label'] or c['end'] is None or c['exclusion']:
                reasons.append(f"contact_{c['id']}:{c['exclusion'] or 'unconfirmed'}")
        if a['epoch'] != b['epoch']:
            reasons.append('continuity_break')
        if a['label'] == b['label']:
            reasons.append('same_foot_label')
        if b['start'] <= a['start']:
            reasons.append('non_positive_step_time')
        if any(a['start'] < s['end_s'] and b['start'] > s['start_s'] for s in summary['stops']):
            reasons.append('stationary_interval')
        rows.append({'from_id': a['id'], 'to_id': b['id'], 'included': not reasons, 'reasons': reasons})
    return rows


def cycle_decisions(summary, origin):
    rows = []
    contacts = [c for c in summary['contacts'] if c.get('candidate_outcome') not in {'excluded_nonstep', 'associated_fragment'}]
    for a, b, c in zip(contacts, contacts[1:], contacts[2:]):
        reasons = []
        for x in (a, b, c):
            if not x['confirmed'] or not x['label'] or x['end'] is None or x['exclusion']:
                reasons.append(f"contact_{x['id']}:{x['exclusion'] or 'unconfirmed'}")
        if len({x['epoch'] for x in (a, b, c)}) != 1:
            reasons.append('continuity_break')
        if not a['label'] == c['label'] != b['label']:
            reasons.append('non_alternating_labels')
        if any(a['start'] < s['end_s'] and c['start'] > s['start_s'] for s in summary['stops']):
            reasons.append('stationary_interval')
        for x in contacts:
            observed_end = x['end'] if x['end'] is not None else x['last'] - origin + .001
            if (x['confirmed'] and x['start'] < c['start']
                    and observed_end > a['start']
                    and (x['exclusion'] or not x['label'] or x['end'] is None or x['epoch'] != a['epoch'])):
                reasons.append(f"overlapping_contact_{x['id']}")
        rows.append({'contact_ids': [a['id'], b['id'], c['id']],
                     'start_s': a['start'], 'end_s': c['start'], 'foot': a['label'],
                     'included': not reasons, 'reasons': reasons})
    return rows


def audit_frames(frames, trace_path, *, accept_degraded=False):
    raw_lookup = {(f.stream_id, f.sample_index): (i, f) for i, f in enumerate(frames)}
    if len(raw_lookup) != len(frames):
        raise ValueError('Duplicate stream/sample identity in source')
    position_samples, sizes, processors, reports = defaultdict(list), {}, [], []
    processed_samples = set()
    original = WalkingProcessor.process
    original_report = WalkingProcessor.build_report

    def observe_report(p, *args, **kwargs):
        report = original_report(p, *args, **kwargs)
        reports.append(report)
        return report
    with trace_path.open('w', newline='', encoding='utf-8') as output:
        writer = csv.writer(output)
        writer.writerow(['source_frame_ordinal_0based', 'stream_id', 'sample_index', 'device_frame_index',
                         'raw_contact_packed_hex', 'filtered_contact_packed_hex', 'valid_packed_hex',
                         'changed_beams', 'quality_flags'])

        def observe(p, frame, observation=None, *, masked_contact=False):
            if observation is not None:
                raise ValueError('This audit supports the production stable10 path only')
            if not processors:
                processors.append(p)
            ordinal, raw = raw_lookup[(frame.stream_id, frame.sample_index)]
            processed_samples.add(frame.sample_index)
            writer.writerow([ordinal, frame.stream_id, frame.sample_index, raw.frame_index,
                             packed(raw.contact_bits), packed(frame.contact_bits), packed(frame.valid_bits),
                             sum(a != b for a, b in zip(raw.contact_bits, frame.contact_bits)),
                             '|'.join(frame.quality_flags)])
            original(p, frame, observation, masked_contact=masked_contact)
            for c in p.contacts:
                previous = sizes.get(c.id, 0)
                for value in c.positions[previous:]:
                    position_samples[c.id].append({
                        'sample_index': frame.sample_index, 'source_frame_ordinal': ordinal,
                        'low_beam': c.low, 'high_beam': c.high, 'stored_m': value,
                        'beam_centre_m': (frame.layout.positions_m[c.low] + frame.layout.positions_m[c.high]) / 2,
                        'raw_blocked_beams_in_range': sum(raw.contact_bits[c.low:c.high + 1]),
                        'filtered_blocked_beams_in_range': sum(frame.contact_bits[c.low:c.high + 1]),
                    })
                sizes[c.id] = len(c.positions)

        with patch.object(WalkingProcessor, 'process', observe), \
                patch.object(WalkingProcessor, 'build_report', observe_report):
            result = replay_session(frames, accept_degraded=accept_degraded)
    if not processors:
        return {'status': 'not_armed', 'replay': result}
    p = processors[0]
    summary = result['summary']
    checks, metrics = verify_summary(summary, p.origin or 0, position_samples)
    # Duration endpoints are exposed separately: association and last-occupied
    # selection are still processor decisions, not independently labelled truth.
    duration = max(0, p.last_occupied + .001 - p.origin) if p.origin is not None and p.last_occupied is not None else None
    confirmed = [c for c in summary['contacts'] if c['confirmed']]
    passage = None
    if (len(confirmed) >= 2 and not summary['issues'] and duration and summary['direction']
            and all(c['label'] and c['end'] is not None and not c['exclusion'] for c in (confirmed[0], confirmed[-1]))):
        passage = abs(confirmed[-1]['position_m'] - confirmed[0]['position_m']) / duration
    metrics.update(duration_s=duration, passage_speed_m_s=passage)
    for name in ('duration_s', 'passage_speed_m_s'):
        actual, expected = summary[name], metrics[name]
        checks.append({'name': name, 'passed': actual is expected if expected is None else
                       actual is not None and bool(np.isclose(actual, expected)),
                       'reported': actual, 'recomputed': expected})
    report = reports[-1]
    for field, expected in {
        'avg_stride': metrics['mean_step_m'] * 100 if metrics['mean_step_m'] is not None else None,
        'avg_velocity': metrics['walking_speed_m_s'] * 100 if metrics['walking_speed_m_s'] is not None else None,
        'avg_single_support': metrics['single_support_s'],
        'avg_double_support': metrics['double_support_s'],
    }.items():
        actual = getattr(report, field)
        checks.append({'name': f'report.{field}', 'passed': actual is expected if expected is None else
                       actual is not None and bool(np.isclose(actual, expected)),
                       'reported': actual, 'recomputed': expected})
    decisions = step_decisions(summary)
    cycles = cycle_decisions(summary, p.origin or 0)
    expected_pairs = [(x['from_id'], x['to_id']) for x in decisions if x['included']]
    reported_pairs = [(x['from_id'], x['to_id']) for x in summary['steps']]
    checks.append({'name': 'step_eligibility', 'passed': reported_pairs == expected_pairs,
                   'reported': reported_pairs, 'recomputed': expected_pairs})
    expected_cycles = [(x['foot'], x['start_s'], x['end_s']) for x in cycles if x['included']]
    reported_cycles = [(x['foot'], x['start_s'], x['end_s']) for x in summary['cycles']]
    checks.append({'name': 'cycle_eligibility', 'passed': reported_cycles == expected_cycles,
                   'reported': reported_cycles, 'recomputed': expected_cycles})
    evidence = []
    for c in p.contacts:
        edges = {}
        for name in ('start', 'end', 'confirmed_at', 'lift_confirmed_at'):
            value = getattr(c, name)
            if value is None:
                edges[name] = None
                continue
            sample = round(value * 1000)
            raw = raw_lookup.get((p.device.stream_id, sample))
            edges[name] = {'sample_index': sample, 'source_frame_ordinal': raw[0] if raw else None,
                           'processed': sample in processed_samples}
            checks.append({'name': f'contact.{c.id}.{name}.source_exists', 'passed': raw is not None})
        evidence.append({'id': c.id, 'edges': edges, 'position_samples': position_samples[c.id]})
    return {'status': 'passed' if all(c['passed'] for c in checks) else 'failed',
            'origin_sample_time_s': p.origin, 'recomputed_metrics': metrics, 'checks': checks,
            'duration_evidence': {'origin_sample': round(p.origin * 1000) if p.origin is not None else None,
                                  'last_occupied_sample': round(p.last_occupied * 1000) if p.last_occupied is not None else None,
                                  'end_exclusive_offset_samples': 1},
            'step_decisions': decisions, 'cycle_decisions': cycles, 'contact_evidence': evidence, 'replay': result,
            'coverage': {'checked': 'beam-coordinate positions, step/cycle eligibility, step/stride arithmetic, contact/support averages, cadence, walking speed, duration endpoints, passage speed, report unit conversions, event source references',
                         'not_independently_validated': 'contact association, filtering correctness, stop detection, last-occupied selection, physical accuracy, anatomical left/right'}}


def write_review(path, audit):
    s = audit.get('replay', {}).get('summary', {})
    labels = dict(valid_steps='有效步数', valid_cycles='有效周期', mean_step_m='平均步长（米）',
                  mean_stride_m='平均跨步长（米）', mean_contact_s='平均接触时间（秒）',
                  single_support_s='平均单支撑（秒）', double_support_s='平均双支撑（秒）',
                  cadence_per_min='步频（步/分）', walking_speed_m_s='行走阶段速度（米/秒）',
                  duration_s='测量时长（秒）', passage_speed_m_s='整趟前进速度（米/秒）')
    def display(value):
        if value is None:
            return '—'
        if isinstance(value, float):
            return f'{value:.6f}'.rstrip('0').rstrip('.')
        return str(value)
    def table(headers, rows):
        return '<table><tr>' + ''.join(f'<th>{html.escape(h)}</th>' for h in headers) + '</tr>' + ''.join(
            '<tr>' + ''.join(f'<td>{html.escape(display(v))}</td>' for v in row) + '</tr>' for row in rows) + '</table>'
    body = '<h1>地面走路：原始帧与报告核对</h1>'
    body += f"<p>核对状态：{html.escape(audit['status'])}。原始文件 SHA256：{audit['source_sha256']}</p>"
    body += '<p>历史记录的软件回放；A/B 是交替接触标签，不是人体左右脚。光栅遮挡不是测力台触地真值。未验证真实测量准确率。</p>'
    body += f"<p>本次回放屏蔽的光束索引（从 0 开始）：{html.escape(str(audit['replay'].get('masked_indices', [])))}；源文件保持不变：{audit['source_unchanged']}。</p>"
    body += '<p><a href="audit.json">完整核对与位置取样</a> · <a href="frames.csv">逐帧原始/过滤位图</a></p>'
    body += '<p>时间以首个确认接触为零点，单位秒；位置单位米。原始帧序号从 0 开始，是协议解析后的帧序号，不是 CSV 行号。位图按每字节低位优先展开。</p>'
    body += '<h2>报告指标复算</h2>' + table(['指标', '复算值'],
        [(labels.get(k, k), v) for k, v in audit.get('recomputed_metrics', {}).items()])
    failed = [c for c in audit.get('checks', []) if not c['passed']]
    body += '<p>失败检查：' + html.escape(str(failed)) + '</p>'
    body += '<h2>接触事件</h2>' + table(['ID', 'A/B', '人体侧别', '落脚', '离脚', '位置', '确认', '排除理由'],
        [[c[k] for k in ('id', 'label', 'side', 'start', 'end', 'position_m', 'confirmed', 'exclusion')] for c in s.get('contacts', [])])
    body += '<h2>相邻接触与有效步</h2>' + table(['起点 ID', '终点 ID', '计入', '排除理由'],
        [[r['from_id'], r['to_id'], r['included'], ', '.join(r['reasons'])] for r in audit.get('step_decisions', [])])
    body += '<p>short_contact：过短接触；ambiguous_contacts：接触混叠；unknown_touch_after_gap：中断后落脚时刻未知；incomplete_contact：离脚未确认；continuity_break：连续性中断。未决候选保留为步序屏障；仅明确结案为excluded_nonstep的候选允许跳过。候选归属与排除仍是算法决策，本页算术复核不验证其物理真实性。</p>'
    body += '<h2>事件原始采样索引</h2>' + table(['接触 ID', '落脚', '离脚', '落脚确认', '离脚确认'],
        [[c['id']] + [c['edges'][k]['sample_index'] if c['edges'][k] else None
                     for k in ('start', 'end', 'confirmed_at', 'lift_confirmed_at')]
         for c in audit.get('contact_evidence', [])])
    body += '<h2>周期</h2>' + table(['脚标签', '起点', '终点', '单支撑秒', '双支撑秒'],
        [[c[k] for k in ('foot', 'start_s', 'end_s', 'single_support_s', 'double_support_s')] for c in s.get('cycles', [])])
    body += '<h2>周期保留与排除</h2>' + table(['三个接触 ID', '计入', '排除理由'],
        [[c['contact_ids'], c['included'], ', '.join(c['reasons'])] for c in audit.get('cycle_decisions', [])])
    body += '<p>单/双支撑按接触区间在设备 1 ms 时钟上重新积分；接触关联、过滤、停步判定和周期筛选仍是算法输出，不能把公式一致当成识别正确。</p>'
    path.write_text('<!doctype html><meta charset="utf-8"><title>走路证据核对</title><style>body{font:16px sans-serif;max-width:1200px;margin:32px auto;padding:20px}table{border-collapse:collapse;margin:16px 0}td,th{border:1px solid #bbb;padding:8px;text-align:left}th{background:#eee}</style>' + body, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--accept-degraded', action='store_true')
    args = parser.parse_args()
    if args.capture.resolve() in {(args.output_dir / name).resolve() for name in ('frames.csv', 'audit.json', 'review.html')}:
        parser.error('Output must not overwrite the input capture')
    app = QCoreApplication.instance() or QCoreApplication([])
    digest = hashlib.sha256(args.capture.read_bytes()).hexdigest()
    frames = load_capture(args.capture)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_frames(frames, args.output_dir / 'frames.csv', accept_degraded=args.accept_degraded)
    audit.update(source=str(args.capture.resolve()), source_sha256=digest,
                 source_unchanged=digest == hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                 source_frames=len(frames), exclusion_counts=dict(Counter(
                     c['exclusion'] or 'included' for c in audit['replay'].get('summary', {}).get('contacts', []))))
    if not audit['source_unchanged']:
        audit['status'] = 'failed'
    (args.output_dir / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    write_review(args.output_dir / 'review.html', audit)
    print(json.dumps({k: audit[k] for k in ('status', 'source_frames', 'source_unchanged', 'exclusion_counts')}, ensure_ascii=False))
    return 0 if audit['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

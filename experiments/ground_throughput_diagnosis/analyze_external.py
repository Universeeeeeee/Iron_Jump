"""External evidence: sample counts and wait-stack existence, never GIL milliseconds."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import numpy as np
from analyze import verify, phase, PHASES, stats

HERE = Path(__file__).resolve().parent


def category(stack):
    for frame in reversed(stack):
        filename = (frame.get('file') or frame.get('args', {}).get('filename') or '').replace('\\', '/').lower()
        if 'hardware/walking_preflight.py' in filename:
            return 'quality_runtime'
        if 'engine/device_quality_session.py' in filename:
            return 'quality_gate'
        if 'hardware/beam_filter.py' in filename or 'hardware/payload_mirror.py' in filename:
            return 'stability_filter'
        if 'engine/modes/' in filename:
            return 'processor'
        if 'engine/overground_session.py' in filename:
            return 'session'
        if ('ui/annotation_canvas.py' in filename and frame.get('name') == '_draw_live_pose') or 'vision/pose_overlay.py' in filename:
            return 'gui_pose_overlay'
        if 'ui/annotation_canvas.py' in filename:
            return 'gui_video_surface'
        if 'ui/embedded_camera_panel.py' in filename:
            return 'gui_preview'
        if '/ui/' in filename or 'fixed_geometry_cache.py' in filename:
            return 'gui_other'
        if '/vision/' in filename:
            return 'vision_python'
        if '/camera/' in filename:
            return 'camera_python'
    return 'other'


def low_cost(delivery, data):
    last = data['milestones'][-1][0]
    mode = data['mode']
    records = [r for r in delivery['low_frequency_spans']
               if r[1] < last and PHASES[mode]['checked'] < r[4] <= PHASES[mode]['last']]
    result = {}
    for part in ('empty_before', 'dense', 'empty_after', 'all'):
        selected = [r for r in records if part == 'all' or phase(mode, r[4]) == part]
        stages = defaultdict(list)
        for r in selected:
            children = [c for c in selected if r[0] == 'snapshot' and c[0] in ('summary', 'visual_emit')
                        and c[5] == r[5] and r[1] <= c[1] and c[2] <= r[2]]
            wall = r[2] - r[1] - sum(c[2] - c[1] for c in children)
            cycles = r[3] - sum(c[3] for c in children)
            assert wall >= 0 and cycles >= 0
            stages[r[0]].append((wall / 1e6, cycles))
        result[part] = {label: {'calls': len(v), 'exclusive_wall_ms_per_call': stats([x[0] for x in v]),
                                'exclusive_cycles_per_call': stats([x[1] for x in v]),
                                'exclusive_wall_total_ms': sum(x[0] for x in v)} for label, v in stages.items()}
    return result


def inspect(folder):
    data, timing, _, _, _, report_sha, evidence_sha = verify(folder)
    marker = json.loads((folder / 'external_marker.json').read_text())
    assert marker['target_result'] == 0 and marker['sampler_result'] == 0
    delivery = json.loads((folder / 'external_delivery.json').read_text())
    helper = HERE / ('state_target.py' if delivery.get('preview_state') else 'external_target.py')
    assert delivery['source_sha256'] == hashlib.sha256(helper.read_bytes()).hexdigest()
    assert delivery['captured_live_overlay'] and (folder / 'live_overlay.png').exists()
    assert sum(r[2] > 0 for r in delivery['draws']) > 10
    output = {'name': folder.name, 'mode': data['mode'], 'kind': marker['kind'],
              'raw_report_runtime_quality_audit_exact': True,
              'canonical_report_sha256': report_sha, 'canonical_evidence_sha256': evidence_sha,
              'live_pose_draws_with_valid_connections': sum(r[2] > 0 for r in delivery['draws']),
              'switch_initial_seconds': delivery['initial_switch_interval_seconds'],
              'switch_final_seconds': delivery['final_switch_interval_seconds'],
              'switch_changes': delivery['switch_changes'],
              'preview_state': delivery.get('preview_state', 'inherited_disabled'),
              'low_frequency': low_cost(delivery, data),
              'performance_not_a_baseline_trial': True}
    lines = (folder / 'sampler.log').read_text(encoding='utf-8', errors='replace').splitlines()
    output['sampler_messages'] = lines[-12:]
    profile = json.loads((folder / 'profile.json').read_text())
    if marker['kind'] == 'gil':
        frames = profile['shared']['frames']
        thread_counts, role_counts, category_counts, leaf_counts = Counter(), Counter(), Counter(), Counter()
        for thread in profile['profiles']:
            thread_counts[thread['name']] += len(thread['samples'])
            match = re.search(r'Thread\s+(0[xX][0-9a-fA-F]+|\d+)', thread['name'])
            tid = int(match[1], 0) if match else None
            role = ('gui' if tid == data['thread_ids']['gui'] else
                    'consumer' if tid == data['thread_ids']['consumer'] else 'other_threads')
            role_counts[role] += len(thread['samples'])
            for sample in thread['samples']:
                stack = [frames[i] for i in sample]
                category_counts[category(stack)] += 1
                if stack:
                    f = stack[-1]
                    leaf_counts[(f.get('file'), f['name'], f.get('line'))] += 1
        output.update(captured_gil_stacks=sum(thread_counts.values()),
                      gil_stacks_by_thread=dict(thread_counts), gil_stacks_by_category=dict(category_counts),
                      gil_stacks_by_role=dict(role_counts),
                      gil_leaf_samples=[{'file': k[0], 'function': k[1], 'line': k[2], 'samples': v}
                                        for k, v in leaf_counts.most_common(25)],
                      scope='Scheduled dense phase; actual captured GIL-owner samples only. No percentage of elapsed time or waiting-thread GIL duration inferred.')
    else:
        stacks = defaultdict(list)
        examples = []
        names = Counter()
        for e in profile:
            stack = stacks[e['tid']]
            if e['ph'] == 'B':
                stack.append(e)
                # Symbolized lock-wait paths in a consumer callback are useful existence evidence.
                active_consumer = any(x['name'] in ('on_frame', 'consume', '_consume', 'process', '_feed')
                                      and any(s in x['args']['filename'].replace('\\', '/')
                                              for s in ('device_quality_session', 'beam_filter', 'session_controller', 'running_processor', 'walking_processor'))
                                      for x in stack)
                if active_consumer and re.search(r'gil|PyEval_RestoreThread|PyThread_acquire|WaitFor|ConditionVariable|Sleep', e['name'], re.I):
                    names[e['name']] += 1
                    if len(examples) < 30:
                        examples.append({'thread': e['tid'], 'ts_us_relative_to_profiler': e['ts'],
                                         'stack': [{'name': x['name'], 'file': x['args']['filename'],
                                                    'line': x['args'].get('line')} for x in stack]})
            elif e['ph'] == 'E':
                assert stack and stack[-1]['name'] == e['name'], (folder.name, 'unbalanced trace')
                stack.pop()
        output.update(trace_events=len(profile), consumer_wait_frame_entries=dict(names),
                      consumer_wait_examples=examples,
                      scope='Frame-entry/existence evidence only. Chrome traces bridge missed/filtered/dead-thread intervals; no hold-time or wait-time totals calculated.')
    print(folder.name, 'verified', output.get('captured_gil_stacks', output.get('trace_events')),
          'pose draws', output['live_pose_draws_with_valid_connections'], flush=True)
    return output


if __name__ == '__main__':
    statuses = json.loads((HERE / 'external_status.json').read_text())
    output = {'statuses': statuses, 'runs': {}}
    for record in statuses:
        name = f"external_{record['mode']}_{record['kind']}_01"
        if record['returncode'] == 0:
            output['runs'][name] = inspect(HERE / 'runs' / name)
    for folder in sorted((HERE / 'runs').glob('enabled_external_*_gil_01')):
        output['runs'][folder.name] = inspect(folder)
    (HERE / 'external_summary.json').write_text(json.dumps(output, indent=2) + '\n')

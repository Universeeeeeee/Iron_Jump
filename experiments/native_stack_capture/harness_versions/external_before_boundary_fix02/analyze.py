"""Fail-closed quality checks on delivered events, not WPR success messages."""
import argparse
import base64
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / 'plan.json').read_text())


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def native_cpu(thread):
    a, b = thread['before'], thread['after']
    return (b['user_100ns'] + b['kernel_100ns'] - a['user_100ns'] - a['kernel_100ns']) / 1e7


def stack_info(parts, symbols):
    users, kernels = [], []
    for part in parts:
        user = tuple(a for a in part if a < 1 << 63)
        kernel = tuple(a for a in part if a >= 1 << 63)
        if user and user not in users: users.append(user)
        if kernel and kernel not in kernels: kernels.append(kernel)
    addresses = [a for part in users for a in part]
    frames = [symbols.get(str(a), dict(module=None, rva=None, symbol=None)) for a in addresses]
    names = [f['symbol'] or '' for f in frames]
    root = len(users) == 1 and bool(names) and any(
        key in names[-1] for key in ('RtlUserThreadStart', 'BaseThreadInitThunk'))
    families = []
    # A low-level waiting API plus its source in a single root-complete user chain.
    low_wait = any('NtWait' in n or 'WaitForSingleObjectEx' in n for n in names)
    if root and low_wait and any('take_gil' in n for n in names): families.append('gil_wait_chain')
    if root and low_wait and any('QWaitCondition::wait' in n or 'QMutex' in n for n in names): families.append('qt_wait_chain')
    if root and any('NtDelayExecution' in n for n in names) and any('SleepEx' in n for n in names): families.append('system_timer_wait_chain')
    return dict(has_user=bool(users), has_kernel=bool(kernels), root_complete=root,
                ambiguous=len(users)>1 or len(kernels)>1, user_depth=len(addresses),
                unknown_symbol_frames=sum(not f['symbol'] for f in frames),
                unmapped_frames=sum(not f['module'] for f in frames), families=families,
                frames=frames)


def clock_residual_ms(anchors, samples, frequency):
    # Every converted timestamp must agree with every observer bracket.
    # ctypes can release the GIL inside a wide bracket; a midpoint is not a measurement.
    if not anchors or not samples:
        raise ValueError('Missing clock evidence')
    bounds = [(a['filetime_100ns']-a['qpc_after']*10000000//frequency,
               a['filetime_100ns']-a['qpc_before']*10000000//frequency) for a in anchors]
    offsets = [s['filetime_100ns']-s['qpc']*10000000//frequency for s in samples]
    return max(max(low-o,o-high,0)/1e4 for low,high in bounds for o in offsets)


def interval_covers_window(intervals,begin,end,required):
    timer=sorted((i for i in intervals if i['source']==0),key=lambda i:i['qpc'])
    previous=[i for i in timer if i['qpc']<=begin]
    return bool(previous) and previous[-1]['new']==required and all(
        i['new']==required for i in timer if begin<i['qpc']<=end)


def quality(case, symbols_file='symbols03.json'):
    fixture, record = read(case/'fixture/fixture.json'), read(case/'record.json')
    roles = {v['before']['tid']: name for name, v in fixture['threads'].items()}
    result = dict(mode=record['mode'], pid=fixture['pid'], threads={}, synthetic_only=fixture['synthetic_only'])
    for tid, role in roles.items():
        t = fixture['threads'][role]
        result['threads'][role] = dict(tid=tid, cpu_s=native_cpu(t), cycles=t['after']['cycles']-t['before']['cycles'],
                                       work=t['work'], sample_events=0, nonprocess_samples=0, joined=0, root_complete=0,
                                       kernel_present=0, ambiguous=0, user_frames=0, unknown_symbol_frames=0,
                                       unmapped_frames=0, max_user_depth=0, families={}, witnesses={})
    if record['mode'] == 'off': return result
    metadata = read(case/'decoded/metadata.json')
    symbols = read(case/symbols_file)
    events_path = case/'decoded/events.jsonl'
    assert hashlib.sha256(events_path.read_bytes()).hexdigest() == symbols['events_sha256']
    stacks, samples, switches, ready, lifecycle = defaultdict(list), [], [], defaultdict(list), defaultdict(list)
    intervals = []
    for line in events_path.read_text().splitlines():
        e = json.loads(line)
        d = base64.b64decode(e['payload'])
        provider, op, version = e['provider'][:8], e['opcode'], e['version']
        if provider == 'def2fe46':
            assert op == 32 and version == 2 and len(d)>=16 and (len(d)-16)%8==0 and e['flags']&0x40, 'Unknown stack shape'
            qpc, pid, tid = struct.unpack_from('<QII',d)
            assert pid == fixture['pid']
            stacks[qpc,tid].append(struct.unpack_from('<'+'Q'*((len(d)-16)//8),d,16))
        elif provider == 'ce1dbfb4' and op == 46:
            assert version == 2 and len(d)==16 and e['flags']&0x40, 'Unknown sample shape'
            ip, tid, count = struct.unpack_from('<QIH',d)
            assert count == 1, 'Weighted samples need explicit decoding'
            samples.append((e['qpc'],tid,ip,bool(d[14]&3)))
        elif provider == 'ce1dbfb4' and op == 72:
            assert version == 2 and len(d)==12
            intervals.append(dict(qpc=e['qpc'], source=struct.unpack_from('<I',d)[0], new=struct.unpack_from('<I',d,4)[0], old=struct.unpack_from('<I',d,8)[0]))
        elif provider == '3d6fa8d1' and op == 36:
            assert version == 5 and len(d)==28, 'Unqualified CSwitch shape'
            new, old = struct.unpack_from('<II',d)
            switches.append((e['qpc'],new,old,d[14],e['cpu']))
        elif provider == '3d6fa8d1' and op == 50:
            assert version == 2 and len(d)==8
            ready[struct.unpack_from('<I',d)[0]].append(e['qpc'])
        elif provider == '3d6fa8d1' and op in (1,2,3,4):
            assert version == 3 and len(d)>=8
            pid, tid = struct.unpack_from('<II',d)
            lifecycle[tid].append((e['qpc'],op,pid))
    freq = metadata['qpc_frequency']
    result['loss'] = {key:metadata[key] for key in ('header_events_lost','consumer_events_lost','buffers_lost')}
    result['interval_events'] = intervals
    result['clock_type'] = metadata['clock_type']
    assert metadata['clock_type'] == 1 and freq == fixture['start']['frequency']
    anchors = [fixture['start'],fixture['end']] + [t[k]['clock'] for t in fixture['threads'].values() for k in ('before','after')]
    result['clock_max_residual_ms'] = clock_residual_ms(anchors,metadata['clock_samples'],freq)
    result['anchor_width_us_max'] = max((a['qpc_after']-a['qpc_before'])/freq*1e6 for a in anchors)
    result['pdb_matched_modules'] = [m['path'] for m in symbols['modules'] if m['pdb_matched']]
    result['kernel_symbols_complete'] = False
    result['sample_ip_not_in_linked_stack'] = 0
    for tid, role in roles.items():
        t, r = fixture['threads'][role], result['threads'][role]
        begin, end = t['before']['clock']['qpc_after'],t['after']['clock']['qpc_before']
        identity = lifecycle[tid]
        r['lifecycle_ok'] = bool(identity) and all(p==fixture['pid'] for _,_,p in identity) and any(q<=begin and op in (1,3) for q,op,_ in identity) and any(q>=end and op in (2,4) for q,op,_ in identity)
        r['creation_unchanged'] = t['before']['creation_100ns'] == t['after']['creation_100ns']
        selected = [(q,ip) for q,x,ip,nonprocess in samples if x==tid and begin<=q<=end]
        r['nonprocess_samples'] = sum(nonprocess for q,x,ip,nonprocess in samples if x==tid and begin<=q<=end)
        r['sample_events'] = len(selected)
        if record['mode'] == 'wait':
            # Delivered CSwitch stacks use NewThreadID and describe the resumed stack.
            # Pair with the preceding switch-out of that same TID; never join to OldThreadID.
            selected = [(q,None) for q,new,old,state,cpu in switches if new==tid and begin<=q<=end]
        for q, ip in selected:
            parts = stacks.get((q,tid),[])
            info = stack_info(parts,symbols['addresses'])
            r['joined'] += bool(parts)
            r['root_complete'] += info['root_complete']
            r['kernel_present'] += info['has_kernel']
            r['ambiguous'] += info['ambiguous']
            r['user_frames'] += info['user_depth']
            r['unknown_symbol_frames'] += info['unknown_symbol_frames']
            r['unmapped_frames'] += info['unmapped_frames']
            r['max_user_depth'] = max(r['max_user_depth'],info['user_depth'])
            for family in info['families']:
                r['families'][family] = r['families'].get(family,0)+1
                if family not in r['witnesses']:
                    r['witnesses'][family] = dict(qpc=q,frames=info['frames'])
            if ip is not None and not any(ip in part for part in parts): result['sample_ip_not_in_linked_stack'] += 1
        r['stack_events_expected'] = len(selected)
        r['association_rate'] = r['joined']/len(selected) if selected else None
        r['user_root_complete_rate'] = r['root_complete']/len(selected) if selected else None
        if record['mode'] == 'cpu':
            r['interval_covers_window'] = interval_covers_window(intervals,begin,end,PLAN['cpu_interval_100ns'])
            r['sample_cpu_s'] = (len(selected)-r['nonprocess_samples'])*PLAN['cpu_interval_100ns']/1e7
            r['cpu_error_s'] = r['sample_cpu_s']-r['cpu_s']
        else:
            running, start, active_cpu, violations, last_out = 0,None,None,[],None
            paired_waits, wait_chain_witnesses = 0,Counter()
            for q,new,old,state,cpu in switches:
                if old == tid:
                    if start is None: violations.append('out_without_in')
                    elif cpu != active_cpu: violations.append('cpu_changed_while_running')
                    else: running += max(0,min(q,end)-max(start,begin))/freq
                    start, active_cpu, last_out = None,None,(q,state)
                if new == tid:
                    if start is not None: violations.append('in_without_out')
                    start, active_cpu = q,cpu
                    if last_out and last_out[1]==5 and begin<=last_out[0]<=q<=end:
                        paired_waits += 1
                        info = stack_info(stacks.get((q,tid),[]),symbols['addresses'])
                        for family in info['families']: wait_chain_witnesses[family]+=1
            r.update(schedule_residency_s=running, schedule_error_s=running-r['cpu_s'], schedule_violations=violations,
                     paired_wait_intervals=paired_waits, paired_wait_chain_counts=dict(wait_chain_witnesses))
    gates = PLAN['gates']
    checks = dict(controller=not record.get('failure') and all(c['returncode']==0 for c in record['commands']),
                  loss_zero=not any(result['loss'].values()), clock=result['clock_max_residual_ms']<=gates['clock_residual_ms_max'],
                  identity=all(t['lifecycle_ok'] and t['creation_unchanged'] for t in result['threads'].values()),
                  cycles=all(t['cycles']>0 for t in result['threads'].values()),
                  association=all(t['association_rate'] is not None and t['association_rate']>=gates['stack_association_min'] for t in result['threads'].values() if t['stack_events_expected']),
                  user_root=all(t['user_root_complete_rate'] is not None and t['user_root_complete_rate']>=gates['user_root_complete_min'] for t in result['threads'].values() if t['stack_events_expected']),
                  unambiguous=not any(t['ambiguous'] for t in result['threads'].values()))
    if record['mode']=='cpu':
        checks.update(interval_restored=record.get('interval_restored_100ns')==record.get('interval_before_100ns') and record.get('interval_readback_100ns')==PLAN['cpu_interval_100ns'],
                      profiles_exclusive=not any(shape.startswith('3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c/36/') or shape.startswith('3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c/50/') for shape in metadata['shapes']),
                      interval_event=any(i['source']==0 and i['new']==PLAN['cpu_interval_100ns'] for i in intervals),
                      counter=all(abs(t['cpu_error_s'])<=max(gates['cpu_vs_threadtimes_absolute_error_s_floor'],t['cpu_s']*gates['cpu_vs_threadtimes_relative_error_max']) for role,t in result['threads'].items() if role.startswith('cpu') or (not fixture['synthetic_only'] and t['cpu_s']>=0.5)),
                      sample_floor=sum(t['sample_events'] for t in result['threads'].values())>=gates['cpu_process_samples_min'],
                      ip_matches_stack=result['sample_ip_not_in_linked_stack']==0,
                      interval_covers_windows=all(t['interval_covers_window'] for t in result['threads'].values()))
    else:
        checks.update(profiles_exclusive=not any(shape.startswith('ce1dbfb4-137e-4da6-87b0-3f59aa102cbc/46/') for shape in metadata['shapes']),
                      events_present=all(t['stack_events_expected']>0 for t in result['threads'].values()),
                      counter=all(abs(t['schedule_error_s'])<=max(gates['schedule_vs_threadtimes_absolute_error_s_floor'],t['cpu_s']*gates['schedule_vs_threadtimes_relative_error_max']) for t in result['threads'].values()),
                      schedule_chain=not any(t['schedule_violations'] for t in result['threads'].values()))
    result['quality_checks'] = checks
    result['quality_pass'] = all(checks.values())
    result['quantitative_field_attribution_ready'] = False
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('case',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    with a.output.open('x') as stream: json.dump(quality(a.case),stream,indent=2)

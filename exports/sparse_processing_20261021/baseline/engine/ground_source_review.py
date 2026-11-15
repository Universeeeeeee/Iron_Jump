"""Bounded, conditional review of late narrow islands beside an established foot."""
from copy import deepcopy

RULE_VERSION = 'late_narrow_front_growth_v1'
SHORT_ISLAND_MS = 30
POST_JOIN_MS = 10


def ownership_record(group):
    return group.get('recovery') or group.get('established_owner')


def assigned_sources(group):
    record = ownership_record(group)
    if not record:
        return set()
    assigned = set(record['source_ids'])
    assigned.update(d['source_id'] for d in group.get('source_decisions', [])
                    if d['outcome'] == 'associated' and d['owner_id'] == record['owner_id'])
    return assigned


def observe_review_frame(p, groups, frame, observation):
    anchors = {c.id: [(c.low,c.high)] for c in p.active
               if p._touch_events.get(c.id, {}).get('active')}
    for g in p._ownership_groups:
        record = ownership_record(g)
        if g['tracking_ended_sample'] is None and record and p._touch_events.get(record['owner_id'], {}).get('active'):
            anchors[record['owner_id']] = g['islands']
    islands = []
    for low,high in groups:
        owners = [owner for owner,spans in anchors.items()
                  if any(low<=b and high>=a for a,b in spans)]
        reliable = (all(frame.valid_bits[low:high+1])
                    and not any(low-1<=i<=high+1 for i in p.device.bad_indices)
                    and (observation is None or observation.reliable(low,high)))
        islands.append([low,high,reliable,owners])
    p._source_review_frames.append([frame.sample_index,islands])


def review_source(p, group, source, record):
    first, joined = source['first_sample'], source['joined_sample']
    e = source['evidence_at_join']
    evidence = {}
    if first is None or not 0 < joined-first <= SHORT_ISLAND_MS:
        return 'outside_short_island_window', evidence
    if (e.get('confirmed') or p._touch_events.get(source.get('contact_id'), {}).get('active')
            or e.get('peak_width_m',0) >= .08
            or any(i != record['owner_id'] for i in group.get('competing_owner_ids', []))):
        return 'independent_mature_source', evidence
    if (e.get('exclusion') or e.get('problem') or e.get('masked_contact') or e.get('has_unknown')
            or e.get('interrupted') or e.get('merged_interruptions') or e.get('edge_estimates') or e.get('clear_gaps')
            or source['valid_sample_intervals'] != [[first,joined]]):
        return 'uncertain_source_history', evidence
    history = source.get('review_observations', [])
    if [n for n,_ in history] != list(range(first,joined)):
        return 'incomplete_source_history', evidence
    owner = record['owner_id']; positions = p.positions
    geometry = []; side = None
    for n,islands in history:
        fragments = [x for x in islands if x[0]<=source['high'] and x[1]>=source['low'] and owner not in x[3]]
        parents = [x for x in islands if x[3]==[owner]]
        if len(fragments)!=1 or len(parents)!=1:
            return 'competing_projection', evidence
        f,body = fragments[0],parents[0]
        if not f[2] or not body[2] or f[3]:
            return 'unreliable_or_owned_source', evidence
        direction = 1 if f[0]>body[1] else -1 if f[1]<body[0] else 0
        if not direction or side is not None and direction!=side:
            return 'incompatible_front_growth', evidence
        side = direction
        if p.direction and side!=p.direction:
            return 'opposite_progression', evidence
        gap = positions[f[0]]-positions[body[1]] if side==1 else positions[body[0]]-positions[f[1]]
        width = positions[f[1]]-positions[f[0]]
        if gap>.035+1e-9 or width>.025+1e-9 or positions[body[1]]-positions[body[0]]<.08:
            return 'incompatible_calibrated_geometry', evidence
        # A third local projection is positive competition, even if unconfirmed.
        if any(x is not f and x is not body and positions[x[0]]<=positions[max(f[1],body[1])]+.035
               and positions[x[1]]>=positions[min(f[0],body[0])]-.035 for x in islands):
            return 'competing_local_source', evidence
        geometry.append([n,body[:2],f[:2],gap])
    for a,b in zip(geometry,geometry[1:]):
        if (b[3]>a[3]+1e-9 or b[1][0]>a[1][1] or b[1][1]<a[1][0]
                or b[2][0]>a[2][1] or b[2][1]<a[2][0]):
            return 'discontinuous_front_growth', evidence
    # Earlier unassigned contributors cannot silently serve as this island's owner.
    if any(s['source_id'] not in assigned_sources(group) and s['source_id']!=source['source_id']
           and s['joined_sample']<joined for s in group['sources']):
        return 'prior_source_unresolved', evidence
    runs = [r for r in group['observation_runs'] if r[1]>joined and r[0]<joined+POST_JOIN_MS]
    if group['last_sample']+1 < joined+POST_JOIN_MS:
        return 'awaiting_post_join_growth', evidence
    cursor=joined; first_shape=None
    for start,end,islands,reliable in runs:
        if max(start,joined)!=cursor or not reliable or len(islands)!=1:
            return 'uncertain_post_join_projection', evidence
        lo,hi=islands[0]
        body,fragment=geometry[-1][1:3]
        if (lo>min(body[0],fragment[0]) or hi<max(body[1],fragment[1])
                or positions[hi]-positions[lo]>.45 or lo==0 or hi==len(positions)-1):
            return 'incompatible_joint_growth', evidence
        first_shape = first_shape or [lo,hi]
        cursor=min(end,joined+POST_JOIN_MS)
    if cursor!=joined+POST_JOIN_MS:
        return 'incomplete_post_join_history', evidence
    first_body=geometry[0][1]
    growth=(positions[first_shape[1]]-positions[first_body[1]] if side==1
            else positions[first_body[0]]-positions[first_shape[0]])
    if growth < min(s.pitch_m for s in p.device.layout.segments)-1e-9:
        return 'insufficient_front_growth', evidence
    evidence.update({'prejoin_geometry':geometry, 'post_join_interval':[joined,joined+POST_JOIN_MS],
                     'front_growth_m':growth, 'short_window_ms':SHORT_ISLAND_MS,
                     'source_valid_intervals':deepcopy(source['valid_sample_intervals']),
                     'interpretation':'conditional_front_growth_not_optical_identity_proof'})
    return None,evidence


def review_group_sources(p, group):
    if group['state']!='observing':
        return
    record=ownership_record(group)
    if record is None:
        mature=[s for s in group['sources'] if s['evidence_at_join'].get('confirmed')
                and p._touch_events.get(s.get('contact_id'),{}).get('active')]
        if len(mature)!=1:
            return
        s=mature[0];owner=p.contacts[s['contact_id']]
        if not owner.touch_known or s['evidence_at_join'].get('has_unknown'):
            return
        record={'owner_id':owner.id,'source_ids':[s['source_id']],
                'original_touch_sample':p._event_sample(owner),
                'recovered_sample':p._touch_events[owner.id]['published_sample'],
                'established_sample':p.last_sample,
                'rule_version':'existing_published_owner_v1'}
        group['established_owner']=record
    for source in group['sources']:
        if source['source_id'] in assigned_sources(group):
            continue
        prior=[d for d in group.get('source_decisions',[]) if d['source_id']==source['source_id']]
        if prior and prior[-1]['outcome']=='unresolved':
            continue
        reason,evidence=review_source(p,group,source,record)
        if prior and prior[-1]['reason']==reason:
            continue
        pending=reason in {'awaiting_post_join_growth','prior_source_unresolved'}
        decision={'source_id':source['source_id'],'owner_id':record['owner_id'],
                  'outcome':'associated' if reason is None else 'pending' if pending else 'unresolved',
                  'evidence_start_sample':source['first_sample'],'joined_sample':source['joined_sample'],
                  'source_valid_sample_intervals':deepcopy(source['valid_sample_intervals']),
                  'reviewed_group_intervals':[[max(a,source['joined_sample']),
                      min(b,source['joined_sample']+POST_JOIN_MS,p.last_sample+1)]
                      for a,b in group['valid_sample_intervals']
                      if max(a,source['joined_sample']) < min(b,source['joined_sample']+POST_JOIN_MS,p.last_sample+1)],
                  'decided_sample':p.last_sample,'rule_version':RULE_VERSION,
                  'reason':reason or 'continuous_late_front_growth','evidence':evidence}
        group.setdefault('source_decisions',[]).append(decision)
        p.event_audit.append({'action':'source_attribution_review','sample':p.last_sample,'group_id':group['id'],**deepcopy(decision)})
        if reason is None and source.get('contact_id') is not None:
            c=p.contacts[source['contact_id']]
            if c.id!=record['owner_id']:
                c.candidate_outcome='associated_fragment'
                if c in p.active:p.active.remove(c)

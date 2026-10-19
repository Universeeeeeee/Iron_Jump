"""Exact controlled call/result identity; never grants performance qualification."""
def inspect(plan,a,b):
    identity=('frame_id','media_sample_s','logical_ms','jpeg_sha256','pixels_sha256','shape')
    checks={}
    for name,value in (('a',a),('b',b)):
        calls=value['calls']
        checks[name+'_closed']=value['close_confirmed'] and not value['errors'] and value.get('complete_calls',False)
        checks[name+'_sequence']=[x['frame_id'] for x in calls]==plan['frame_ids'] and [x['logical_ms'] for x in calls]==[1000+i*50 for i in range(len(plan['frame_ids']))]
        checks[name+'_wall_order']=all(x['decoded_ns']<=x['begin_ns']<=x['end_ns'] for x in calls) and all(x['end_ns']<=y['begin_ns'] for x,y in zip(calls,calls[1:]))
    checks['same_call_work']=[[x[k] for k in identity] for x in a['calls']]==[[x[k] for k in identity] for x in b['calls']]
    checks['same_complete_results']=[(x['has_pose'],x['result_content_sha256']) for x in a['calls']]==[(x['has_pose'],x['result_content_sha256']) for x in b['calls']]
    return dict(checks=checks,controlled_model_identity_pass=all(checks.values()),actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)

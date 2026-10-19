"""Observe the original canvas tuple after original painting has completed."""
def observe(widget,stats):
    stats['all']+=1
    if widget._live_pose is None:return
    overlay,size=widget._live_pose
    nodes=overlay['nodes']
    valid=any(nodes[a]['valid'] and nodes[b]['valid'] for a,b in overlay['connections'])
    stats['valid']+=int(valid);stats['disabled_calls']+=int(not widget.isEnabled())

def paint_then_observe(original,widget,painter,rect,stats,errors):
    result=original(widget,painter,rect)
    try:observe(widget,stats)
    except Exception as exc:errors.append('draw_observation:'+repr(exc))
    return result

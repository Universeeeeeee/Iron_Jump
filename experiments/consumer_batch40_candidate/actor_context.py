"""Same original actor with two consumer-phase context reads; no policy changes."""
import json
from pathlib import Path
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def run_actor_context(connection,input_root,output_root):
    sys.path.insert(0,str(ROOT/'experiments/session_gui_vision'));sys.path.insert(0,str(HERE))
    from actor import run_actor
    from context import Phases,restore
    from ui.session_controller import _GroundFrameInbox
    rows=[];plan=json.loads((HERE/'plan02.json').read_text());observer=Phases(rows,plan['context_checkpoints']);originals=observer.install(('consumer',))
    original_drain=_GroundFrameInbox.drain
    def drain(inbox):
        deadline=time.perf_counter()+.004
        while True:
            with inbox._lock:items=[inbox._pending.popleft() for _ in range(min(plan['batch_size'],len(inbox._pending)))]
            inbox._consume(items)
            if not items or time.perf_counter()>=deadline:break
        with inbox._lock:pending=bool(inbox._pending)
        interval=0 if pending else 5
        if inbox._timer.interval()!=interval:inbox._timer.setInterval(interval)
    _GroundFrameInbox.drain=drain
    try:return run_actor(connection,input_root,output_root)
    finally:
        _GroundFrameInbox.drain=original_drain
        restore(originals)
        folder=Path(output_root)
        if folder.exists():
            with (folder/'phase_context.json').open('x') as f:json.dump(rows,f,indent=2)

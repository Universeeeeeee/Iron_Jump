"""Same original actor with two consumer-phase context reads; no policy changes."""
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def run_actor_context(connection,input_root,output_root):
    sys.path.insert(0,str(ROOT/'experiments/session_gui_vision'));sys.path.insert(0,str(HERE))
    from actor import run_actor
    from context import Phases,restore
    rows=[];plan=json.loads((HERE/'plan02.json').read_text());observer=Phases(rows,plan['context_checkpoints']);originals=observer.install(('consumer',))
    try:return run_actor(connection,input_root,output_root)
    finally:
        restore(originals)
        folder=Path(output_root)
        if folder.exists():
            with (folder/'phase_context.json').open('x') as f:json.dump(rows,f,indent=2)

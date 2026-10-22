"""Independent QPC cross-process offset bounds, without frames or GUI."""
import json,multiprocessing,sys,time
from pathlib import Path
from replay_support import clock_echo
if __name__=='__main__':
    context=multiprocessing.get_context('spawn');parent,child=context.Pipe();process=context.Process(target=clock_echo,args=(child,));process.start();child.close();implementation=parent.recv();samples=[]
    for _ in range(32):
        before=time.perf_counter_ns();parent.send(True);c1,c2=parent.recv();after=time.perf_counter_ns();samples.append(dict(parent_send=before,child_receive=c1,child_send=c2,parent_receive=after,offset_low_ns=c2-after,offset_high_ns=c1-before))
    parent.send(None);process.join(5);assert process.exitcode==0;low=max(s['offset_low_ns'] for s in samples);high=min(s['offset_high_ns'] for s in samples)
    result=dict(parent_implementation=time.get_clock_info('perf_counter').implementation,child_implementation=implementation,offset_low_ns=low,offset_high_ns=high,zero_offset_admissible=low<=0<=high,bound_width_ns=high-low,samples=samples)
    assert result['zero_offset_admissible'] and result['bound_width_ns']<1_000_000
    Path(sys.argv[1]).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='samples'}))

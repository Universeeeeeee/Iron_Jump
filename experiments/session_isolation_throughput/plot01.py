"""Standalone descriptive figure; no extrapolated performance comparison."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    result=read(HERE/'result01.json');stage=ROOT/'experiments/session_gui_vision/runs/evidence02/runs02';actor=read(stage/'client/actor/result.json');rows=actor['queue_common'];arm=actor['armed'][0]
    with np.load(stage/'client/actor/raw_frames.npz') as z:first=int(z['sample_indices'][0]);begin=int(z['received_ns'][0]);indices=z['sample_indices'].copy();received=z['received_ns'].copy()
    previous_d=first-1;bounds=[]
    for row in rows:bounds.append(row[5]-previous_d);previous_d=row[5]-row[3]
    fig,axes=plt.subplots(2,1,figsize=(10,7),layout='constrained')
    ax=axes[0];edges=[(begin-arm)/1e9]+[(r[0]-arm)/1e9 for r in rows]
    ax.stairs(bounds,edges,fill=True,color='#d6e6fb',label='Conservative continuous deque upper bound')
    ax.scatter([(r[0]-arm)/1e9 for r in rows],[r[3] for r in rows],s=7,color='#195d9f',label='Locked observations (peak lower bound)')
    dense=np.searchsorted(indices,[59904,66904]);ax.axvspan((int(received[dense[0]])-arm)/1e9,(int(received[dense[1]])-arm)/1e9,color='#eab859',alpha=.17,label='Frozen dense + mixed source phase')
    ax.set(xlabel='Seconds after formal arm',ylabel='Queued frames',title='Existing isolated-session window: continuous deque peak is between 26 and 93')
    ax.set_ylim(bottom=0);ax.legend(fontsize=8,loc='upper left');ax.grid(alpha=.2)
    ax=axes[1];events=result['contacts'];x=np.arange(len(events));ax.bar(x-.18,[v['source_touch_to_paint_ms'] for v in events],width=.36,label='Receipt touch to original paint',color='#3682c5')
    ax.bar(x+.18,[v['scheduled_touch_to_paint_ms'] for v in events],width=.36,label='Scheduled touch to original paint',color='#db9348')
    ax.axhline(250,color='#555555',ls='--',lw=1,label='Legacy absolute reference (not new acceptance)')
    ax.set(xticks=x,xticklabels=[str(v['contact_id']) for v in events],xlabel='Active publication contact ID (not human step count)',ylabel='Milliseconds',title='All nine active publication IDs painted; worst scheduled latency 193.5 ms')
    ax.set_ylim(0,310);ax.legend(fontsize=8,loc='upper left');ax.grid(axis='y',alpha=.2)
    fig.suptitle('Saved Walk + original GUI/model + simulated SDK; one posthoc descriptive window',fontsize=12)
    fig.savefig(HERE/'throughput01.png',dpi=160);plt.close(fig)

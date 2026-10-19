"""Show every fixed case and conservative peak bounds, including failed cases."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    plan=read(HERE/'plan02.json');result=read(HERE/'result01.json');cases=plan['cases'];x=np.arange(len(cases))
    colors={'original':'#d78d40','isolated':'#377db7'}
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,layout='constrained')
    for i,c in enumerate(cases):
        v=result['cases'][c['id']]
        if 'scheduled_max_ms' not in v:
            for ax in axes:ax.text(i,2,'failed' if v.get('failed') else 'not attempted',rotation=90,ha='center',fontsize=8)
            continue
        axes[0].bar(i,v['scheduled_max_ms'],color=colors[c['backend']],width=.65)
        lo,hi=v['observed_queue_lower'],v['queue_upper']
        axes[1].vlines(i,max(1,lo),max(1,hi),color=colors[c['backend']],lw=3)
        axes[1].scatter([i,i],[max(1,lo),max(1,hi)],color=colors[c['backend']],s=14)
    for ax in axes:
        ax.set_yscale('symlog',linthresh=100);ax.set_ylim(bottom=0);ax.axhline(250,color='#555',ls='--',lw=1)
        ax.axvline(3.5,color='#555',ls=':',lw=1);ax.grid(axis='y',alpha=.2)
        ax.legend(handles=[Patch(color=colors[k],label=k) for k in colors],loc='upper right')
    axes[0].set(ylabel='Worst scheduled touch to paint (ms)',title='Four same-backend A/A windows, then four counterbalanced A/B pairs')
    axes[1].set(ylabel='Continuous FIFO peak bounds (frames)',title='Segments show observed lower / conservative continuous upper bounds, not confidence intervals')
    labels=[c['id'].replace('original','O').replace('isolated','I') for c in cases]
    axes[1].set_xticks(x,labels,rotation=35,ha='right');axes[1].set_xlabel('Every fixed case retained; dashed lines are legacy absolute limits')
    decision=result['symptom_decision'];label='incomplete' if decision is None else 'advance' if decision['advance'] else 'no advance'
    fig.suptitle('Saved Walk + original GUI/model + simulated SDK | controlled symptom decision: '+label,fontsize=12)
    fig.savefig(HERE/'comparison01.png',dpi=150);plt.close(fig)

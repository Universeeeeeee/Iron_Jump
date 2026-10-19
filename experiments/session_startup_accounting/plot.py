"""Raw enclosing wall/CPU ledger view; CPU totals are not waiting shares."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    r=json.loads((HERE/'result01.json').read_text());names=list(r['cases']);x=np.arange(len(names))
    fig,axes=plt.subplots(3,1,figsize=(10,9),layout='constrained')
    for ax,key,title in zip(axes,('model_open','caller_before_first_through_100','consumer_dense_to_mixed'),('Model open enclosing account','Caller before first base call through call 100','Consumer dense-to-mixed progress (6000-6007 frames)')):
        a=[r['cases'][n]['accounts'][key] for n in names]
        wall=[sum(z['wall_ns_bounds'])/2e9 for z in a];thread=[z['thread']['cpu_ms']/1000 for z in a];process=[z['process']['cpu_ms']/1000 for z in a]
        ax.bar(x-.24,wall,width=.24,color='#71899e',label='Enclosing wall (bound midpoint)')
        ax.bar(x,thread,width=.24,color='#d78d40',label='Caller / named thread CPU')
        if key!='consumer_dense_to_mixed':ax.bar(x+.24,process,width=.24,color='#347db5',label='Whole-process CPU (includes workers)')
        ax.set(xticks=x,xticklabels=names,ylabel='Seconds',title=title);ax.grid(axis='y',alpha=.2);ax.legend(fontsize=8,loc='upper right');ax.set_ylim(bottom=0)
    fig.suptitle('Four passive saved-GUI windows: CPU accounts also change in the slow first window',fontsize=12)
    fig.supxlabel('Bars are not additive. Process CPU may exceed wall; wall minus thread CPU is not GIL waiting.',fontsize=10)
    fig.savefig(HERE/'ledger01.png',dpi=150);plt.close(fig)

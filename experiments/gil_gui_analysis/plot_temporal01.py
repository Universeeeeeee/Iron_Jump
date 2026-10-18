"""Standalone scientific plot of existing witnesses; lines do not interpolate evidence."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from temporal_review01 import read,sha


def main(a):
    result=read(a.result);fig,axes=plt.subplots(2,2,figsize=(12,7.6),sharex=True,sharey='row')
    sources={'temporal_result':sha(a.result),'plotter':sha(Path(__file__))}
    for col,(label,root,stage,color) in enumerate([('prior',a.prior,'off_aa01','#ba312a'),('repeat',a.repeat,'restart_repeat01','#276fbf')]):
        base=root/'experiments/gil_gui_calibration/runs'/stage
        slow=read(base/'pair01_a/capture/measurement.json');report=read(base/'pair01_a/capture/report.json')
        with np.load(base/'pair01_a/capture/raw_frames.npz') as raw:
            bits=raw['bits'].astype(bool)&raw['valid_bits'].astype(bool);bits[:,report['report_config_snapshot']['device']['bad_indices']]=False
            occupied=np.any(bits,axis=1)&(raw['sample_indices']>report['report_config_snapshot']['device']['checked_sample_index']);received=raw['received_ns'].copy()
        changes=np.diff(np.r_[False,occupied,False].astype(int));starts=np.flatnonzero(changes==1);ends=np.flatnonzero(changes==-1)
        for ax in axes[:,col]:
            for start,end in zip(starts,ends):
                ax.axvspan((int(received[start])-slow['armed_ns'])/1e9,(int(received[min(end,len(received)-1)])-slow['armed_ns'])/1e9,color='#37956a',alpha=.08)
            ax.axvspan(12,17,color='#d69523',alpha=.08);ax.grid(alpha=.2);ax.set_xlim(0,27)
        for folder in sorted(base.glob('pair*')):
            m=read(folder/'capture/measurement.json');rows=m['queue_common'];x=[(r[0]-m['armed_ns'])/1e9 for r in rows];y=[r[3] for r in rows]
            is_slow=folder.name=='pair01_a';axes[0,col].plot(x,y,color=color if is_slow else '#888888',alpha=.95 if is_slow else .25,lw=1.5 if is_slow else .7,label='First case' if is_slow else None)
            if is_slow:axes[0,col].scatter(x,y,color=color,s=4,alpha=.4)
        axes[0,col].set_yscale('symlog',linthresh=100);axes[0,col].set_ylim(0,4500);axes[0,col].set_title('Earlier cohort' if label=='prior' else 'After reported device restart')
        for name,shift,c in [('pair01_a',-.10,color),('pair01_b',.10,'#333333')]:
            bins=result['cases'][label+'/'+name]['host_bins']
            valid=[b for b in bins if b['batch_completed_frame_count_bounds'] is not None]
            xs=[b['host_second']+.5+shift for b in valid];lower=[b['batch_completed_frame_count_bounds'][0] for b in valid];upper=[b['batch_completed_frame_count_bounds'][1] for b in valid]
            axes[1,col].vlines(xs,lower,upper,color=c,lw=1.5,label='First-case completion bounds' if name=='pair01_a' else 'Next-case completion bounds')
            axes[1,col].plot(xs,lower,'_',color=c,ms=4);axes[1,col].plot(xs,upper,'_',color=c,ms=4)
        bins=result['cases'][label+'/pair01_a']['host_bins'];axes[1,col].scatter([b['host_second']+.5 for b in bins],[b['source_generated_frames'] for b in bins],s=8,color='#555555',marker='.',label='Source-generated frames')
        axes[1,col].axhline(1000,color='#333333',lw=.5,ls=':');axes[1,col].set_ylim(0,2700);axes[1,col].set_xlabel('Host seconds after armed')
        axes[0,col].legend(loc='upper left',fontsize=8);axes[1,col].legend(loc='upper left',fontsize=7)
    axes[0,0].set_ylabel('Observed pending frames (symlog)');axes[1,0].set_ylabel('Frame counts in a fixed 1-second bin')
    fig.suptitle('Saved fixed Walk replay: contact-stage deficit and later catch-up',fontsize=12)
    fig.text(.5,.025,'Shared queue probe retained; external stack sampler OFF. Green: raw source contact; orange: native counter window.\nPoints/bounds are witnesses; lines only guide the eye. First cases retained; others grey. No CPU/GIL/Qt shares.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.08,1,.95));assert not a.output.exists();fig.savefig(a.output,dpi=180);plt.close(fig)
    with a.output.with_suffix('.json').open('x') as f:json.dump(sources,f,indent=2)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True);p.add_argument('--prior',type=Path,required=True);p.add_argument('--repeat',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())

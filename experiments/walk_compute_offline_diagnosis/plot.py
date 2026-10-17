"""Standalone scientific figure from accepted JSON; refuses output overwrite."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent


def main(output):
    assert not output.exists()
    a = json.loads((HERE / 'aligned03.json').read_text())
    s = json.loads((HERE / 'windows_summary01.json').read_text())
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw={'width_ratios': [1, 1.2]})
    for i, t in enumerate(a['trials']):
        y = 3 - i
        x = t['contact_input_receipt_span_formal_s']
        axs[0].plot(x, [y + .1] * 2, color='#2677ad', lw=6, label='Input receipt span' if i == 0 else None)
        outer = t['windows_formal_s']['contact_span_outer'][0]
        inner = t['windows_formal_s']['contact_span_inner'][0]
        axs[0].plot(outer, [y - .1] * 2, color='#eea654', lw=6, alpha=.4, label='Completion outer bounds' if i == 0 else None)
        axs[0].plot(inner, [y - .1] * 2, color='#da771c', lw=6, label='Completion inner span' if i == 0 else None)
    axs[0].set(yticks=range(4), yticklabels=['4 OFF', '3 ON', '2 ON', '1 OFF'], xlabel='Seconds after arm', title='Actual filtered-contact samples')
    axs[0].legend(fontsize=8, loc='upper right')
    axs[0].set_xlim(6, 25)
    for j, stage in enumerate(['quality', 'filter', 'processor']):
        values = [t['stages'][stage]['contact_core']['wall_us_per_raw_input'] for t in s['trials']]
        med = np.array([v['median'] for v in values])
        low = np.array([v['min'] for v in values])
        high = np.array([v['max'] for v in values])
        axs[1].errorbar(np.arange(4) + (j - 1) * .15, med, yerr=np.array([med - low, high - med]), fmt='o', capsize=3, label=stage)
    axs[1].set(xticks=range(4), xticklabels=['1 OFF', '2 ON', '3 ON', '4 OFF'], ylabel='Wall microseconds / raw input', title='Windows isolated stage replays (3 repeats)')
    axs[1].legend(fontsize=8)
    axs[1].set_ylim(0, 260)
    for ax in axs:
        ax.grid(alpha=.2)
    fig.suptitle('Consumption alignment and offline cost variation — no live CPU/GIL attribution', fontsize=12)
    fig.tight_layout()
    fig.savefig(output, dpi=170)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('output', type=Path)
    main(p.parse_args().output)

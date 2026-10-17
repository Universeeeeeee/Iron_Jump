"""Standalone scientific figure from saved results, no runtime imports."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main(source, output):
    assert not output.exists()
    data = json.loads(source.read_text())
    fig, axes = plt.subplots(5, 2, figsize=(14, 13), sharex=True, layout='constrained')
    colors = ['#2878b5', '#e49d22', '#96b7b5']
    fps_limit = max(v['queue']['consumer_fps'] for t in data['ON_trials'] for v in t['per_second']) * 1.1
    for column, trial in enumerate(data['ON_trials']):
        seconds = trial['per_second']
        x = np.array([v['second'] + .5 for v in seconds])
        axes[0, column].set_title('Walk ON ' + str(column + 2) + ' | ' + trial['case'].split('_')[1])
        axes[0, column].plot(x, [v['queue']['pending']['max'] for v in seconds], label='pending peak', color='#bd4242')
        axes[0, column].set_ylim(0, 5500)
        axes[0, column].set_ylabel('Pending frames')
        axes[1, column].plot(x, [v['queue']['consumer_fps'] for v in seconds], label='completed fps', color='#2878b5')
        axes[1, column].plot(x, [v['received_frames'] for v in seconds], label='received frames/s', color='#888888', linestyle='--')
        axes[1, column].set_ylabel('Frames / second')
        axes[1, column].set_ylim(0, fps_limit)
        axes[1, column].legend(loc='upper right', fontsize=8)
        axes[2, column].stackplot(x, *[[v['threads']['consumer']['fraction'][state] * 100 for v in seconds]
                                     for state in ('Running', 'Ready', 'Waiting')],
                                  labels=['Running residency', 'Ready', 'Waiting'], colors=colors)
        axes[2, column].set_ylim(0, 100)
        axes[2, column].set_ylabel('Consumer state %')
        axes[2, column].legend(loc='upper right', fontsize=8)
        axes[3, column].plot(x, [v['input_contact_fraction'] for v in seconds], label='input contact', color='#6d57a3')
        axes[3, column].plot(x, [v['completed_contact_fraction'] for v in seconds], label='completed contact', color='#d28e44')
        axes[3, column].set_ylabel('Contact fraction')
        axes[3, column].set_ylim(-.05, 1.1)
        axes[3, column].legend(loc='upper right', fontsize=8)
        visual = trial['actual_visual_intervals']
        mid = [(v['start_formal_s'] + v['end_formal_s']) / 2 for v in visual]
        rate = [v['actual_visual_delta']['valid_pose_draws'] / (v['end_formal_s'] - v['start_formal_s']) for v in visual]
        axes[4, column].plot(mid, rate, color='#287d4f', label='actual valid skeleton draws/s')
        axes[4, column].set_ylim(0, 30)
        axes[4, column].set_ylabel('Skeleton draws / s')
        axes[4, column].set_xlabel('Seconds after formal arm')
        axes[4, column].legend(loc='upper right', fontsize=8)
        for row in range(5):
            a, b = trial['window_formal_seconds']['input_dense']
            axes[row, column].axvspan(a, b, color='#d0b873', alpha=.16)
            axes[row, column].grid(alpha=.2)
            axes[row, column].set_xlim(0, 41)
    fig.suptitle('Existing single-USB Walk traces | shaded: input-dense interval\nRunning is scheduled residency, not exclusive CPU; completion counters are batch observations.', fontsize=12)
    fig.savefig(output, dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    main(args.source, args.output)

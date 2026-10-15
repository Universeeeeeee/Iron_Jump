"""Descriptive plots; all slow rounds retained and probe failure visible."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / 'summary.json').read_text())
colors = {'M': '#2468ad', 'D': '#d77121'}
fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), constrained_layout=True)
for ax, mode in zip(axes, ('run', 'walk')):
    for level in ('M', 'D'):
        values = [data['runs'][f'aa_{mode}_{block:02d}_{level}']['receipt_to_paint_ms']['p95'] for block in range(1, 7)]
        ax.plot(range(1, 7), values, 'o-', color=colors[level], label='Minimal observer (M)' if level == 'M' else 'Diagnostic observer (D)')
    ax.axhline(150, color='#777777', linestyle=':', linewidth=1)
    ax.set(title=mode.capitalize() + (' (7 touches / trial)' if mode == 'run' else ' (10 touches / trial)'),
           xlabel='Paired block', ylabel='Receipt-to-paint P95 (ms)', yscale='log', xticks=range(1, 7))
    ax.grid(alpha=.2)
axes[0].legend(fontsize=8)
fig.suptitle('Inherited disabled-preview replay: D calibration FAILED; timing is exploratory', fontsize=11)
fig.savefig(HERE / 'calibration.png', dpi=170)
plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(11, 4.1), constrained_layout=True)
for ax, mode in zip(axes, ('run', 'walk')):
    runs = [r for r in data['runs'].values() if r['mode'] == mode and r['level'] == 'M']
    for phase, marker, color in (('empty_before', 's', '#29976f'), ('dense', 'o', '#2468ad')):
        ax.scatter([r['phases'][phase]['consumer_fps'] for r in runs],
                   [r['phases'][phase]['age_slope_ms_per_device_second'] for r in runs],
                   s=48, marker=marker, color=color, label=phase.replace('_', ' '), alpha=.8)
    ax.axvline(1000, color='#777777', linestyle=':', linewidth=1)
    ax.axhline(0, color='#777777', linestyle=':', linewidth=1)
    ax.set(title=mode.capitalize(), xlabel='Consumer frames / wall second',
           ylabel='Queue-age slope (ms / device second)')
    ax.grid(alpha=.2)
axes[0].legend(fontsize=8)
fig.suptitle('Inherited disabled-preview replay, original NumPy and M observer', fontsize=11)
fig.savefig(HERE / 'minimal_phases.png', dpi=170)
plt.close(fig)

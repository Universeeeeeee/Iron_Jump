"""Measure the sampled observer's empty-tree floor; never infer an app speedup."""
import ast
import ctypes
import json
from pathlib import Path
from statistics import median
from types import SimpleNamespace
import time

HERE = Path(__file__).resolve().parent
kernel = ctypes.PyDLL('kernel32')
kernel.QueryThreadCycleTime.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64))
kernel.QueryThreadCycleTime.restype = ctypes.c_int
spans = []
local = SimpleNamespace(stack=[], sample=0)
tree = ast.parse((HERE / 'probe.py').read_text(encoding='utf-8'))
definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'call', 'cycles'}]
exec(compile(ast.Module(body=definitions, type_ignores=[]), str(HERE / 'probe.py'), 'exec'), globals())


def noop():
    pass


def parent(children):
    for _ in range(children):
        call('leaf', noop, (), {})


if __name__ == '__main__':
    results = []
    for children in (0, 1, 2, 4, 8, 16):
        spans.clear()
        for i in range(2000):
            local.sample = i
            call('parent', parent, (children,), {})
        roots = [s for s in spans if s[2] is None]
        leaves = [s for s in spans if s[2] is not None]
        results.append({'direct_noop_children': children,
                        'root_exclusive_wall_ns_median': median(s[7] for s in roots),
                        'root_exclusive_cycles_median': median(s[10] for s in roots),
                        'root_inclusive_wall_ns_median': median(s[5] - s[4] for s in roots),
                        'root_inclusive_cycles_median': median(s[9] for s in roots),
                        'leaf_wall_ns_median': median(s[7] for s in leaves) if leaves else None,
                        'leaf_cycles_median': median(s[10] for s in leaves) if leaves else None})
    output = {'results': results,
              'scope': 'Noop observer floor only, no GUI/GIL competition. Do not mechanically subtract from GUI durations or call this an algorithm microbenchmark. Both selected-frame perturbation and parent bookkeeping exist even when average A/A perturbation is small.'}
    (HERE / 'observer_floor.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output, indent=2), flush=True)

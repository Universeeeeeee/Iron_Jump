"""Current-input equivalence gate before each independently scored experiment."""
import json
import sys
import traceback
from experiment import *


def main():
    label,variant=sys.argv[1:3]
    rows=[]
    for case in ('empty','sparse','cross','plateau','stress'):
        layout,frames=synthetic(case,6500)
        for mode in ('walk','run'):
            row=correctness(case,layout,frames,mode,variant)
            rows.append(row);print(json.dumps(row),flush=True)
    for case,mode in (('field_run_20261015_02','run'),('field_walk_full_02','walk')):
        layout,frames,meta=recorded(case)
        row=correctness(case,layout,frames,mode,variant,meta)
        rows.append(row);print(json.dumps(row),flush=True)
    dump(HERE/f'{label}_correctness.json',{'results':rows,'all_exact':True,
         'frame_comparisons':sum(r['frames'] for r in rows),'source_verification':verify_sources()})


if __name__=='__main__':
    try:main()
    except BaseException:
        traceback.print_exc();sys.exit(1)

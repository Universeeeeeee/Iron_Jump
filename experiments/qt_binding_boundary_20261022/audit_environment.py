"""Read launch evidence and conservative file-time overlap bounds after runs."""
import hashlib
import json
from pathlib import Path

here = Path(__file__).resolve().parent
out = here / 'evidence'
desktop = Path('C:/Users/86150/Desktop/IronJump-正式程序.cmd')
test = out / 'tests_pyside6.log'
test_start, test_end = test.stat().st_ctime_ns, test.stat().st_mtime_ns
windows = []
for log in (out / 'matrix03').glob('0*.log'):
    start, end = log.stat().st_ctime_ns, log.stat().st_mtime_ns
    windows.append(dict(case=log.stem, log_created_ns=start, log_last_write_ns=end,
                        test_log_interval_overlaps=max(start, test_start) <= min(end, test_end)))
result = dict(desktop_launcher=dict(path=str(desktop), sha256=hashlib.sha256(desktop.read_bytes()).hexdigest(),
                                    text=desktop.read_text(encoding='utf-8')),
              test_overlap=dict(test_log=str(test), created_ns=test_start, last_write_ns=test_end,
                                windows=windows,
                                limitation='File creation/final write bound launch/log activity, not precise CPU execution. Conservatively exclude overlapping windows from clean causal comparisons; retain all results.'))
with (out / 'environment_audit.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, ensure_ascii=False))

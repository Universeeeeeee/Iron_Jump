"""Exactly one already-frozen four-window task cohort, observed by owned WPR."""
from pathlib import Path
import subprocess
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(HERE/'cohort.ps1')],cwd=HERE)
    raise SystemExit(p.returncode)

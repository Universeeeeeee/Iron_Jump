"""Independent full tracerpt scan + exact ETL/source hashes after synthetic recording."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    results={}
    for folder in sorted((HERE/'runs').iterdir()):
        etl=folder/'trace.etl'
        if not (folder/'fixture/fixture.json').exists() or not etl.exists(): continue
        summary=folder/'tracerpt_summary.txt'
        if not summary.exists():
            r=subprocess.run(['tracerpt',str(etl),'-o','NUL','-summary',str(summary),'-y'],capture_output=True)
            (folder/'tracerpt_process.json').write_text(json.dumps(dict(returncode=r.returncode,stdout=r.stdout.decode(errors='replace'),stderr=r.stderr.decode(errors='replace')),indent=2)+'\n')
            if r.returncode: raise RuntimeError(folder.name)
        symbols=folder/'symbols03.json'
        if not symbols.exists():
            subprocess.run([sys.executable,str(HERE/'symbolize.py'),str(folder/'decoded/events.jsonl'),str(symbols)],check=True)
        results[folder.name]=dict(etl_bytes=etl.stat().st_size,etl_sha256=sha(etl),
                                  source_etl=str(etl),decoded_sha256=sha(folder/'decoded/events.jsonl'),
                                  symbols_sha256=sha(symbols),record_sha256=sha(folder/'record.json'),
                                  tracerpt_summary_sha256=sha(summary))
    with (HERE/'scan_manifest.json').open('x') as stream:
        json.dump(dict(cases=results,post_recording_tool_sha256={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.cs','.wprp','.exe')}),stream,indent=2)


if __name__=='__main__':main()

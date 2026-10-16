"""Offline ETL validation: full summary scan plus the delivered ETL header.

Only the header XML export is deliberately stopped early, after one complete
header event. The original ETL and full-scan summary are preserved unchanged.
No scheduler-state interpretation is attempted for binary CSwitch v5 payloads.
"""
import concurrent.futures,hashlib,json,re,subprocess,time,xml.etree.ElementTree as ET
from pathlib import Path
HERE=Path(__file__).resolve().parent

def validate(item):
    name=item['name'];etl=HERE/(name+'.etl');summary=HERE/(name+'_summary.txt')
    if not summary.exists():
        r=subprocess.run(['tracerpt.exe',str(etl),'-o','NUL','-of','XML','-summary',str(summary),'-y'],capture_output=True,timeout=180)
        (HERE/(name+'_decode.txt')).write_bytes(r.stdout+r.stderr);assert r.returncode==0
    text=summary.read_text(encoding='utf-8-sig');lost=int(re.search(r'Total Events\s+Lost\s+(\d+)',text)[1])
    counts={}
    for opcode,label in [('36','CSwitch'),('ReadyThread','ReadyThread')]:
        rows=re.findall(r'\|\s*(\d+)\s+Thread\s+0\s+'+opcode+r'\s+\d+\s+\{3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c\}',text,re.I)
        counts[label]=sum(map(int,rows));assert counts[label]>0
    prefix=HERE/(name+'.header_work.xml');header_path=HERE/(name+'_header.xml')
    if not header_path.exists():
        if not prefix.exists():
            with (HERE/(name+'_header_export.txt')).open('wb') as log:
                proc=subprocess.Popen(['tracerpt.exe',str(etl),'-o',str(prefix),'-of','XML','-y'],stdout=log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline and (not prefix.exists() or prefix.stat().st_size<262144):
                        if proc.poll() is not None:break
                        time.sleep(.1)
                finally:
                    if proc.poll() is None:proc.terminate()
                    proc.wait(timeout=15)
        # tracerpt holds an exclusive writer handle: read only after it closes.
        with prefix.open('rb') as f:chunk=f.read(262144)
        begin=chunk.find(b'<Event xmlns=');end=chunk.find(b'</Event>',begin)
        assert begin>=0 and end>=0,'No complete ETL header'
        header_path.write_bytes(chunk[begin:end+8]);prefix.unlink()
    header=ET.fromstring(header_path.read_bytes());ns={'e':'http://schemas.microsoft.com/win/2004/08/events/event'}
    fields={v.attrib['Name']:v.text.strip() for v in header.findall('./e:EventData/e:Data',ns)}
    losses={k:int(fields[k]) for k in ('EventsLost','BuffersLost')}
    assert losses['EventsLost']==lost
    status=(HERE/(name+'_trace_status.txt')).read_text(encoding='utf-8-sig')
    keywords=all(v in status for v in ('CSwitch','ReadyThread','ProcessThread','Loader'))
    result={'passed':lost==0 and all(v==0 for v in losses.values()) and keywords,'event_counts':counts,'full_scan_events_lost':lost,'header_losses':losses,'requested_keywords_in_collector':keywords,'etl_bytes':etl.stat().st_size,'etl_sha256':hashlib.file_digest(etl.open('rb'),'sha256').hexdigest(),'summary_sha256':hashlib.file_digest(summary.open('rb'),'sha256').hexdigest(),'header_export_scope':'First complete header event only; XML exporter stopped intentionally afterward. Full event counts/loss scan is separate tracerpt -o NUL summary. Original ETL unchanged.','cswitch_payload_decoded':False,'limits':'CSwitch v5 is binary in installed schema; no Running/Ready/Waiting or GIL/GC attribution.'}
    (HERE/(name+'_trace_validation.json')).write_text(json.dumps(result,indent=2)+'\n');print(name,result['passed'],counts,flush=True)

if __name__=='__main__':
    assert json.loads((HERE/'batch_complete.json').read_text())['completed']==12
    trials=[v for v in json.loads((HERE/'plan.json').read_text())['trials'] if v['trace']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(validate,trials))

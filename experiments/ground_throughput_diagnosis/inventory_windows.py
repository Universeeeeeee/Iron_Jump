"""Closed-evidence byte inventory and raw-camera index validation; after field tests."""
import csv,hashlib,json,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

result={'host':'LAPTOP-N03I4GMH','root':str(HERE),'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'files':[],'field_media':{}}
for folder in sorted((HERE/'runs').iterdir()):
    if not folder.is_dir():continue
    for path in sorted(folder.rglob('*')):
        if path.is_file():result['files'].append({'path':str(path.relative_to(HERE)),'size':path.stat().st_size,'sha256':sha(path)})
for name in ('live_walk_07','live_run_02'):
    folder=HERE/'runs'/name
    timing=json.loads((folder/'timing.json').read_text(encoding='utf-8'))
    delivery=json.loads((folder/'live_delivery.json').read_text(encoding='utf-8'))
    assert timing['finished'] and not timing['errors'] and delivery['system_exit_code']==0
    with (folder/'camera.csv').open() as stream:rows=list(csv.DictReader(stream))
    offset=0;previous=-1
    with (folder/'camera.mjpg').open('rb') as stream:
        for i,row in enumerate(rows,1):
            assert int(row['record_frame_index'])==i and int(row['offset'])==offset
            assert int(row['capture_frame_index'])>previous
            assert int(row['length'])>4
            stream.seek(offset);assert stream.read(2)==b'\xff\xd8'
            stream.seek(offset+int(row['length'])-2);assert stream.read(2)==b'\xff\xd9'
            offset+=int(row['length']);previous=int(row['capture_frame_index'])
    assert offset==(folder/'camera.mjpg').stat().st_size
    result['field_media'][name]={'indexed_JPEG_packets':len(rows),'bytes':offset,'csv_offsets_contiguous_and_JPEG_boundaries_exact':True,'camera_mjpg_sha256':sha(folder/'camera.mjpg'),'camera_csv_sha256':sha(folder/'camera.csv'),'record_elapsed_last_s':float(rows[-1]['record_elapsed_seconds']),'scope':'Original camera bytes and index, no re-encoding or deletion. Not a screen scanout measurement.'}
assert not (HERE/'runs/live_run_01').exists(),'Discarded running round must stay deleted'
result['discarded_live_run_01_absent']=True
(HERE/'windows_evidence_inventory.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'files':len(result['files']),'field_media':result['field_media'],'discarded_live_run_01_absent':True}),flush=True)

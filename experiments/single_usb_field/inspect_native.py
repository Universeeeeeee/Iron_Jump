"""Extract original JPEG packets from a closed native recording; no reencoding."""
import argparse,csv,json
from pathlib import Path

def main(folder,offsets):
    read=lambda name:json.loads((folder/name).read_text(encoding='utf-8-sig'))
    m=read('measurement.json');start=read('camera_record_start.json');origin=(start['before_ns']+start['after_ns'])/2
    assert read('camera_record_end.json')['stats']['recording']==0
    with (folder/'camera.csv').open() as f:rows=list(csv.DictReader(f))
    frames=[]
    with (folder/'camera.mjpg').open('rb') as video:
        for offset in offsets:
            elapsed=(m['armed_ns']-origin)/1e9+offset;r=min(rows,key=lambda v:abs(float(v['record_elapsed_seconds'])-elapsed))
            video.seek(int(r['offset']));data=video.read(int(r['length']));assert data[:2]==b'\xff\xd8' and data[-2:]==b'\xff\xd9'
            name=f'native_formal_{offset:02d}s.jpg';p=folder/name
            if p.exists():assert p.read_bytes()==data
            else:p.write_bytes(data)
            frames.append({'formal_offset_s':offset,'CSV_row':r,'file':name})
    output={'start_bracket_ns':[start['before_ns'],start['after_ns']],'method':'Native steady-clock start bracket midpoint, no drift correction; visual inspection only. Original JPEG packets unchanged.','frames':frames}
    p=folder/'native_inspection.json';value=json.dumps(output,indent=2)
    assert not p.exists(),'Preserve existing inspection metadata';p.write_text(value)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('offsets',type=int,nargs='+');a=p.parse_args();main(a.folder,a.offsets)

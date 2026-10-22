from pathlib import Path
import struct,json,hashlib
r=Path('E:/OptoJump/preview_delay_review_20261022');inv=json.loads((r/'inventory.json').read_text(encoding='utf-8'));results=[]
def boxes(data,start,end):
 while start+8<=end:
  size,kind=struct.unpack_from('>I4s',data,start);header=8
  if size==1:size=struct.unpack_from('>Q',data,start+8)[0];header=16
  if size==0:size=end-start
  if size<header or start+size>end:break
  yield kind,start+header,start+size
  start+=size
def children(data,node,kind):return [n for n in boxes(data,node[1],node[2]) if n[0]==kind]
for n,v in enumerate(inv['videos'],1):
 data=Path(v['path']).read_bytes();root=(b'root',0,len(data));moov=children(data,root,b'moov')[0];tracks=[]
 for trak in children(data,moov,b'trak'):
  mdia=children(data,trak,b'mdia')[0];hdlr=children(data,mdia,b'hdlr')[0]
  if data[hdlr[1]+8:hdlr[1]+12]!=b'vide':continue
  mdhd=children(data,mdia,b'mdhd')[0];offset=20 if data[mdhd[1]]==1 else 12;scale=struct.unpack_from('>I',data,mdhd[1]+offset)[0];minf=children(data,mdia,b'minf')[0];stbl=children(data,minf,b'stbl')[0];stts=children(data,stbl,b'stts')[0];count=struct.unpack_from('>I',data,stts[1]+4)[0];entries=[struct.unpack_from('>II',data,stts[1]+8+i*8) for i in range(count)];tracks.append(dict(timescale=scale,stts_entries=entries,samples=sum(c for c,d in entries),duration_s=sum(c*d for c,d in entries)/scale,constant_30fps=all(d/scale==1/30 for c,d in entries)))
 results.append(dict(video=n,path=v['path'],sha256=hashlib.sha256(data).hexdigest(),tracks=tracks))
(r/'mp4_timing.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))

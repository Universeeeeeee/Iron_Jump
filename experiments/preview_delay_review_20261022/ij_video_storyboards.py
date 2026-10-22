from pathlib import Path
import json,cv2,numpy as np
r=Path('E:/OptoJump/preview_delay_review_20261022');inventory=json.loads((r/'inventory.json').read_text(encoding='utf-8'))
for index,row in enumerate(inventory['videos'],1):
 v=cv2.VideoCapture(row['path']);times=np.linspace(0,max(0,row['duration_s']-.1),16);tiles=[]
 for t in times:
  v.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000);ok,frame=v.read()
  if not ok:continue
  frame=cv2.resize(frame,(640,360));tile=np.zeros((390,640,3),np.uint8);tile[30:]=frame;cv2.putText(tile,f'video {index}   {t:.2f}s',(10,23),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),1);tiles.append(tile)
 v.release();sheet=np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]);cv2.imwrite(str(r/f'storyboard{index}.jpg'),sheet)
for item in inventory['runs']:
 p=Path(item['path']);report=json.loads((p/'actor/report.json').read_text(encoding='utf-8'));s=report.get('walking_summary',{});out=dict(folder=p.name,status=json.loads((p/'status.json').read_text()),actor=json.loads((p/'actor/result.json').read_text()),summary={k:v for k,v in s.items() if k not in ('contacts','footfalls','event_publications','event_audit','visual_timeline')},config=report.get('report_config_snapshot'),publication_events=s.get('event_publications'),event_audit=s.get('event_audit'),footfalls=s.get('footfalls'),timeline=report.get('visual_timeline'))
 (r/(p.name+'_summary.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('Storyboards and run metadata ready')

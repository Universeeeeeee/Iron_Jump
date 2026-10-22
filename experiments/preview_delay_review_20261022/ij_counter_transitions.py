from pathlib import Path
import cv2,json,numpy as np
r=Path('E:/OptoJump/preview_delay_review_20261022');j=json.loads((r/'inventory.json').read_text(encoding='utf-8'));out=[]
for index,row in enumerate(j['videos'],1):
 v=cv2.VideoCapture(row['path']);templates=[];states=[];y=145 if index==2 else 157;n=0
 while True:
  ok,f=v.read()
  if not ok:break
  hsv=cv2.cvtColor(f[y:y+78,320:500],cv2.COLOR_BGR2HSV);mask=((hsv[:,:,1]<40)&(hsv[:,:,2]>200)).astype(np.uint8)
  distances=[np.mean(mask!=t['mask']) for t in templates]
  if distances and min(distances)<.003:
   state=int(np.argmin(distances));templates[state]['seen']+=1
  else:
   state=len(templates);templates.append(dict(mask=mask.copy(),image=f[y:y+78,320:500].copy(),first_s=n/row['fps'],seen=1))
  states.append(state);n+=1
 v.release();tiles=[]
 for k,t in enumerate(templates):
  if t['seen']<3:continue
  tile=np.zeros((115,360,3),np.uint8);tile[35:113]=cv2.resize(t['image'],(360,78));cv2.putText(tile,f'id{k} {t["first_s"]:.3f}s n={t["seen"]}',(4,25),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1);tiles.append(tile)
 while len(tiles)%4:tiles.append(np.zeros_like(tiles[0]))
 cv2.imwrite(str(r/f'counter_templates{index}.jpg'),np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]))
 transitions=[dict(state=k,time_s=n/row['fps']) for n,k in enumerate(states) if (n==0 or k!=states[n-1])]
 out.append(dict(video=index,templates=[dict(state=k,first_s=t['first_s'],frames=t['seen']) for k,t in enumerate(templates)],transitions=transitions))
(r/'counter_transitions.json').write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps([dict(video=x['video'],templates=x['templates']) for x in out]))

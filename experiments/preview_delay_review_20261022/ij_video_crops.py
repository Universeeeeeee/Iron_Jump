from pathlib import Path
import json,cv2
r=Path('E:/OptoJump/preview_delay_review_20261022');j=json.loads((r/'inventory.json').read_text(encoding='utf-8'))
for n,row in enumerate(j['videos'],1):
 v=cv2.VideoCapture(row['path']);v.set(cv2.CAP_PROP_POS_MSEC,(10 if n<3 else 30)*1000);ok,f=v.read();v.release()
 if ok:cv2.imwrite(str(r/f'native{n}.jpg'),f)

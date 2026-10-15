"""Review outbound screen-recording frames only; never count the off-lane return."""
import cv2,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=Path('/Users/vae/Projects/Iron_Jump/现场测试/10.15晚')
OUT=HERE/'runs/screen_review'
OUT.mkdir(exist_ok=True)
# Bounded outbound inspection only. Bounds selected from the captured passage,
# app elapsed banner and raw contact interval; no physical touchdown latency inferred.
PLAN=[('walk','走路共10步-右脚迈入.mp4',8.4,14.8,[9,10,11,12,13,14.6]),
      ('run','跑步共8步右脚迈入.mp4',7.4,11.6,[7.8,8.4,9,9.6,10.4,11.4])]
metadata=[]
for mode,name,start,end,times in PLAN:
    path=BASE/name;capture=cv2.VideoCapture(str(path));fps=capture.get(cv2.CAP_PROP_FPS)
    frames=int(capture.get(cv2.CAP_PROP_FRAME_COUNT));images=[];samples=[]
    for seconds in times:
        capture.set(cv2.CAP_PROP_POS_FRAMES,round(seconds*fps));ok,frame=capture.read();assert ok
        target=OUT/f'{mode}_{seconds:g}.png';cv2.imwrite(str(target),frame)
        images.append(cv2.resize(frame,(640,344)));samples.append({'seconds_nominal':seconds,'decoded_frame_index':int(capture.get(cv2.CAP_PROP_POS_FRAMES))-1,'png':str(target.relative_to(HERE))})
    cv2.imwrite(str(OUT/(mode+'_outbound_sheet.png')),cv2.vconcat([cv2.hconcat(images[i:i+2]) for i in range(0,len(images),2)]))
    capture.release()
    metadata.append({'mode':mode,'filename':name,'source':str(path),'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),'fps':fps,'frames':frames,'duration_nominal_s':frames/fps,'outbound_review_range_s':[start,end],'extracted':samples,'scope':'Outbound only; off-lane return excluded. Screen recording embeds a delayed camera preview, so it is not synchronized physical touchdown ground truth.'})
(HERE/'screen_sources.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
print('Outbound screen frames extracted; originals untouched.')

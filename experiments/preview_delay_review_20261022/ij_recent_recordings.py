from pathlib import Path
import json,datetime
import cv2
r=Path('D:/86150/Videos/屏幕录制');videos=sorted((p for p in r.iterdir() if p.suffix.lower() in ('.mp4','.mkv','.avi','.mov')),key=lambda p:p.stat().st_mtime,reverse=True)[:3];rows=[]
for p in videos:
 v=cv2.VideoCapture(str(p));fps=v.get(cv2.CAP_PROP_FPS);count=v.get(cv2.CAP_PROP_FRAME_COUNT);rows.append(dict(path=str(p),bytes=p.stat().st_size,modified=datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(),fps=fps,frames=count,duration_s=count/fps if fps else None,width=v.get(cv2.CAP_PROP_FRAME_WIDTH),height=v.get(cv2.CAP_PROP_FRAME_HEIGHT)));v.release()
root=Path('E:/OptoJump/Iron_Jump/data/capture_logs/measurements');runs=[]
if root.exists():
 for p in sorted(root.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True)[:8]:
  runs.append(dict(path=str(p),modified=datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(),files=[str(f.relative_to(p)) for f in p.rglob('*') if f.is_file() and f.suffix in ('.json','.log')]))
out=Path('E:/OptoJump/preview_delay_review_20261022');out.mkdir(exist_ok=True);result=dict(videos=rows,runs=runs);(out/'inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result))

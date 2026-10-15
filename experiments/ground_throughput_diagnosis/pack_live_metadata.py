"""Copy closed field evidence without duplicating the large raw camera stream."""
import json,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
name=sys.argv[1]
assert all(c.isalnum() or c=='_' for c in name)
folder=HERE/'runs'/name
assert json.loads((folder/'timing.json').read_text(encoding='utf-8'))['finished']
assert json.loads((folder/'live_delivery.json').read_text(encoding='utf-8'))['system_exit_code']==0
with zipfile.ZipFile(HERE/'runs'/(name+'_metadata_v2.zip'),'x',zipfile.ZIP_DEFLATED) as archive:
    for file in folder.iterdir():
        if file.is_file() and file.suffix!='.mjpg':archive.write(file,name+'/'+file.name)
print('metadata archived',name,flush=True)

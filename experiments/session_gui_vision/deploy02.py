from pathlib import Path
import zipfile
h=Path(__file__).resolve().parent
with zipfile.ZipFile(h/"source02.zip") as z:
 for n in z.namelist():
  f=h/n;data=z.read(n)
  if f.exists():assert f.read_bytes()==data,n
  else:
   with f.open("xb") as out:out.write(data)

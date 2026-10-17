"""Hash complete Windows evidence; package structured exports while retaining ETL in place."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main(a):
    if a.output.exists() or a.manifest.exists():raise FileExistsError('Preserve previous export')
    files=[]
    with zipfile.ZipFile(a.output,'x',zipfile.ZIP_DEFLATED) as archive:
        for name in ['external_runs','external_runs_v2']:
            for path in sorted((a.root/name).rglob('*')):
                if not path.is_file():continue
                relative=str(path.relative_to(a.root)).replace('\\','/')
                packaged=path.suffix.lower()!='.etl'
                files.append(dict(path=relative,bytes=path.stat().st_size,sha256=sha(path),in_structured_package=packaged))
                if packaged:archive.write(path,relative)
    result=dict(source_root=str(a.root),files=files,structured_package_sha256=sha(a.output),
                native_reader_sha256=sha(a.root/'ReadStacks.exe'),ETLs_retained_on_Windows=True)
    a.manifest.write_text(json.dumps(result,indent=2)+'\n')
    print('EXPORTED',len(files),'entries; ETLs remain at source')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path);p.add_argument('manifest',type=Path);main(p.parse_args())

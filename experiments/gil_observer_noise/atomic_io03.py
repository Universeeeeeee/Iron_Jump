"""Publish single-writer Windows handshake JSON only after it is fully written."""
import json
import os


def write(path,value):
    if path.exists():raise FileExistsError(path)
    staged=path.with_name(path.name+'.partial')
    with staged.open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2)
        f.flush();os.fsync(f.fileno())
    # Same-directory NTFS rename publishes atomically and refuses an existing
    # destination on Windows. Each private output path has exactly one writer.
    staged.rename(path)

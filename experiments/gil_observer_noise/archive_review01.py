"""Read Windows manifest paths on any host, preserving the original manifest bytes."""
import hashlib
import json
from pathlib import PureWindowsPath


def manifest_paths(manifest):
    paths={}
    for name,digest in manifest.items():
        p=PureWindowsPath(name)
        if p.is_absolute() or p.drive or p.root or '..' in p.parts or not p.parts:raise ValueError('Unsafe manifest path')
        key=p.as_posix()
        if key.casefold() in {n.casefold() for n in paths}:raise ValueError('Ambiguous manifest path')
        paths[key]=digest
    return paths


def verify_manifest(root):
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8-sig'))
    paths=manifest_paths(manifest)
    assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in paths.items())
    return paths

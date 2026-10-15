import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
manifest=json.loads((Path(__file__).parent/'package_manifest.json').read_text())
wrong=[name for name,sha in manifest.items() if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha]
assert not wrong,wrong
print('Verified exact files:',len(manifest),flush=True)

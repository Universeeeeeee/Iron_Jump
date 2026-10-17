"""Final read-only verification of frozen images, cached PDBs and original ETLs."""
import argparse
import json
from pathlib import Path

from pe_identity import sha, pdb


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main(args):
    assert not args.output.exists()
    inventory = read(args.inventory)
    assert all(sha(image['path'])==image['sha256'] for image in inventory['images']), 'Runtime binary changed'
    base = read(args.field_root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(sha(args.field_root/path)==digest for path,digest in base.items()), 'Field source changed'
    cache = [pdb(p) for p in sorted((Path.cwd()/'symbols').rglob('*.pdb'))]
    probes = read(Path('resolve_ready01.json'))
    for module in probes['modules']:
        assert sha(module['path'])==module['image_sha256']
        if module.get('SymType')==3:
            identity = pdb(module['loaded_pdb'])
            assert identity['guid']==module['loaded_guid'] and identity['age']==module['PdbAge'] and not module['PdbUnmatched']
    cases = ['20261017_112623_8416401b_walk_on','20261017_113358_00ae9eca_walk_on']
    etls = {}
    for case in cases:
        folder = args.field_root/'experiments/single_usb_human_etw/runs'/case
        expected = read(folder/'schedule_trace_validation.json')['etl_sha256']
        assert sha(folder/'schedule.etl')==expected
        etls[case] = expected
    result = {'runtime_image_files_unchanged':len(inventory['images']), 'field_source_files_unchanged':len(base),
              'cached_pdbs':cache,'accepted_resolver_pdbs_rechecked':sum(m.get('SymType')==3 for m in probes['modules']),
              'source_etl_sha256_verified':etls,
              'accepted_sources_and_binary_sha256':{n:sha(n) for n in ['ReadImages_v4.cs','ReadImages_v4.exe','pe_identity.py','resolve.py','historical.py','inventory.py','verify_preflight.py']},
              'scope':'Static verification only; no ETW recording, sampling, capture or target process attachment.'}
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('VERIFIED',result['runtime_image_files_unchanged'],result['field_source_files_unchanged'],len(cache))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--field-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())

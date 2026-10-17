"""Explicit coverage gates. Symbol success never implies live wait attribution."""
import argparse
import json
import ntpath
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pdb_matches(codeview, identity):
    return (codeview['guid'].upper(),codeview['age']) == (identity['guid'].upper(),identity['age'])


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main(output):
    assert not output.exists()
    exact, exports = read(HERE/'resolve_ready01.json'),read(HERE/'resolve_exports01.json')
    inventory = read(HERE/'inventory_compact01.json')
    byname = {ntpath.basename(v['path']).lower():v for v in inventory['images']}
    result = []
    for module in exact['modules']:
        name = ntpath.basename(module['path']).lower()
        pdb_info = module.get('pdb_identity_independent')
        match = bool(pdb_info and module.get('SymType')==3 and not module['PdbUnmatched'] and
                     any(pdb_matches(cv,pdb_info) for cv in byname[name]['codeview']) and
                     module['loaded_guid']==pdb_info['guid'] and module['PdbAge']==pdb_info['age'])
        if module.get('SymType')==3:
            assert match, ('PDB engine and independent identity disagree',name)
        text_ranges = [s for s in byname[name]['sections'] if s['name']=='.text']
        symbols = [s for s in module['symbols'] if s['tag'] in (5,10) and s['roundtrip_name']==s['name'] and s['roundtrip_displacement']==0
                   and any(section['rva']<=s['rva']<section['rva']+section['virtual_size'] for section in text_ranges)]
        fallback = next(m for m in exports['modules'] if ntpath.basename(m['path']).lower()==name)
        result.append({'module':name,'image_sha256':module['image_sha256'],'matched_pdb':match,
                       'pdb_identity':pdb_info, 'source_lines':module.get('LineNumbers'),
                       'function_symbols_enumerated':module.get('function_symbol_count'),
                       'diagnostic_functions':[{'name':s['name'],'rva':s['rva'],'size':s['size'],'source':s.get('source'),
                                                  'interior_roundtrip':s.get('interior_roundtrip')} for s in symbols],
                       'fallback_symbol_type':fallback.get('SymType'),'fallback_diagnostic_names':[s['name'] for s in fallback['symbols']],
                       'coff_symbol_table_count':byname[name]['coff_symbol_table_count'], 'unwind_table':byname[name].get('unwind_table')})
    python = next(m for m in result if m['module']=='python311.dll')
    critical = ['take_gil','drop_gil','PyThread_acquire_lock_timed','PyEval_RestoreThread','_PyEval_EvalFrameDefault']
    assert python['matched_pdb'] and all(any(s['name']==name and s['source'] for s in python['diagnostic_functions']) for name in critical)
    qt = next(m for m in result if m['module']=='qt6core.dll')
    assert qt['matched_pdb'] and any('QWaitCondition::wait' in s['name'] for s in qt['diagnostic_functions'])
    system = [m for m in result if m['module'] in ('ntdll.dll','kernelbase.dll')]
    assert len(system)==2 and all(m['matched_pdb'] for m in system)
    assert any(s['name']=='NtWaitForSingleObject' for m in system for s in m['diagnostic_functions'])
    assert any(s['name']=='WaitForSingleObjectEx' for m in system for s in m['diagnostic_functions'])
    value = {'scope':'Offline symbol and PE metadata readiness only; no live stack capture, performance calibration or causal diagnosis.',
             'gil_and_ordinary_python_lock_functions_distinguishable_by_symbols':True,
             'Qt_sync_functions_have_matching_symbols':True,'Windows_wait_functions_have_matching_symbols':True,
             'NumPy_MediaPipe_OpenCV_internal_kernel_symbols_ready':False,
             'actual_recorded_unwind_completeness_verified':False,'new_tracking_perturbation_calibrated':False,
             'quantitative_live_attribution_ready':False,
             'modules':result,
             'future_gates':['Recheck exact image/PDB identities and process/thread ownership before any future recording.',
                             'Calibrate low-frequency CPU-stack profile and necessary wait-stack profile independently; do not proceed with quantitative attribution after failed calibration.',
                             'Require actual complete caller chains and report unknown/truncated coverage; exported names or module presence are insufficient to claim GIL.',
                             'Align to existing consumer batch state and completed filtered-contact brackets, not merely input density.',
                             'Keep opaque NumPy/MediaPipe/OpenCV internal PCs as module+RVA; do not label a specific compute kernel or infer algorithm-exclusive CPU.']}
    output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('output',type=Path)
    main(p.parse_args().output)

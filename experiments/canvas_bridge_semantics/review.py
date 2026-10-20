"""Verify actual archived canvas bytes, preserving the failed first fixture."""
import hashlib
import json
from pathlib import Path
import zipfile
from check import check

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    old=read(HERE/'result01.json');data=read(HERE/'result02.json');plan=read(HERE/'plan02.json')
    assert not old['passed'] and old['Qt_messages']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert data['plan_sha256']==sha(HERE/'plan02.json')
    check(data,plan)
    process=read(HERE/'control02.status.json')
    assert process['confirmed_exit'] and process['observation_complete'] and process['native_exit_code']==process['managed_exit_code']==0
    assert (HERE/'control02.stderr.log').read_bytes()==b''
    meta=read(HERE/'transport02.json');archive=HERE/'runs02/evidence02.zip';assert sha(archive)==meta['sha256']
    checked=[]
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('manifest02.json'))
        assert len(manifest['files'])==meta['manifest_files']
        assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in manifest['files'].items())
        assert all(n+'/' in z.namelist() for n in meta['locks'])
        for n,v in plan['sources'].items():assert manifest['files'][n]==v
        assert json.loads(z.read('result01.json'))==old
        for row in data['cases']:
            pixels=[]
            for mode in ('original','bridge'):
                raw=z.read(f"runs02/{row['id']}_{mode}.argb");m=row[mode]
                assert hashlib.sha256(raw).hexdigest()==m['pixels_sha256']
                assert len(raw)==m['byte_count']==m['stride']*m['height']
                assert m['width']==980 and m['height']==552 and m['stride']==3920
                pixels.append(raw)
            assert pixels[0]==pixels[1]
            checked.append(dict(id=row['id'],full_bytes_equal=True,bytes_per_mode=len(pixels[0])))
        reference=z.read('runs02/pose_original.argb')
        assert all(z.read(f'runs02/recovery_{mode}.argb')==reference for mode in ('original','bridge'))
        fonts=data['font_delivery'];assert fonts['font_delivery_pass'] and fonts['glyph_runs']
        for row in fonts['rasters']:
            name='left' if row['text']=='左脚' else 'right'
            assert hashlib.sha256(z.read(f'runs02/font_{name}.argb')).hexdigest()==row['sha256']
        assert all(all(i>0 for i in r['glyph_indices']) and r['nonempty_outlines']==len(r['glyph_indices']) for r in fonts['glyph_runs'])
    post=read(HERE/'post02.json');assert post['sources_modules_formal_unchanged'] and not post['live']
    result=dict(real_canvas_finite_semantics_pass=True,archived_pixel_cases=checked,recovery_pixels_independently_equal=True,
        font_glyph_and_raster_delivery_verified=True,original_failed_fixture_retained=True,original_method_unchanged=data['original_method_unchanged'],
        exit_code=0,locks_retained=meta['locks'],
        missing_before_causal_AB=['Real model updates delivered through the GUI while the experimental base call runs.',
            'Concurrent update/lifecycle and callback behavior in the complete saved-input GUI, with original reports and resource closure.',
            'Frozen single-boundary AB with severe-baseline reproduction gate; no fast-state substitution.'],
        performance_AB_started=False,root_cause_or_fix_complete=False,actual_load_disturbance_pass=False,
        bindings={p.name:sha(p) for p in (Path(__file__),HERE/'plan01.json',HERE/'plan02.json',HERE/'result01.json',HERE/'result02.json',HERE/'post02.json',HERE/'transport02.json')})
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))

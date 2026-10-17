"""Static historical image cross-check; never loads a target DLL."""
import argparse
import ctypes as c
import json
import ntpath
from pathlib import Path
import struct

from pe_identity import pe, sha


def dos_map():
    kernel = c.WinDLL('kernel32',use_last_error=True)
    result = {}
    for drive in ['C:','D:','E:']:
        text = c.create_unicode_buffer(32768)
        if kernel.QueryDosDeviceW(drive,text,len(text)):
            result[text.value] = drive
    return result


def main(args):
    assert not args.output.exists()
    mapping = dos_map()
    smoke = json.loads(args.inventory.read_text())
    images = {str(Path(v['path'])).lower():v for v in smoke['images']}
    trials, additions = [], []
    selected = {'libmediapipe.dll','cv2.pyd','Qt6Svg.dll','Qt6OpenGL.dll','Qt6OpenGLWidgets.dll','Qt6DataVisualization.dll','Qt6Test.dll'}
    for file in args.traces:
        trace = json.loads(file.read_text()); records = []
        for row in trace['images']:
            path = row['filename']
            for source,target in mapping.items():
                if path.lower().startswith(source.lower()+'\\'):
                    path = target+path[len(source):]
                    break
            current = images.get(str(Path(path)).lower())
            if current is None and ntpath.basename(path) in selected and Path(path).exists():
                current = pe(path); current['loaded_in_library_smoke'] = False
                images[str(Path(path)).lower()] = current
                additions.append(current)
            if current is None:
                continue
            # Version-3 rundown timestamp is zero in these traces, not mismatch.
            assert current['image_size'] == row['image_size'] and current['checksum'] == row['checksum'], path
            if row['timestamp']:
                assert row['timestamp'] == current['timestamp'],path
            records.append({'filename':row['filename'],'pid':row['pid'],'opcode':row['opcode'],'image_base':row['image_base'],
                            'image_size':row['image_size'],'checksum':row['checksum'],'trace_timestamp':row['timestamp'],
                            'current_sha256':current['sha256'],'path':current['path'],
                            'identity_limit':'Size/checksum/path compatibility only. Zero historical timestamp and no saved historical SHA do not prove byte identity.'})
        trials.append({'source':str(file),'trace_decode_sha256':sha(file),'target_pid':trace['target_pid'],
                       'related_processes':trace.get('related_processes',[]),'matched_records':records})
    extended = dict(smoke);extended['images'] = list(images.values())
    extended['scope'] += ' Additional historical GUI modules read as PE data only, not imported.'
    extended['historical_crosscheck'] = trials
    extended['dos_device_map'] = mapping
    # COFF table and unwind metadata check independent from DbgHelp symbol naming.
    for image in extended['images']:
        data = Path(image['path']).read_bytes()
        head = struct.unpack_from('<I',data,60)[0]
        pointer,count = struct.unpack_from('<II',data,head+12)
        image['coff_symbol_table_count'] = count
        pdata = next((s for s in image['sections'] if s['name']=='.pdata'),None)
        if image['machine']=='0x8664' and pdata:
            table = data[pdata['raw_offset']:pdata['raw_offset']+pdata['virtual_size']]
            assert len(table)%12==0
            entries = list(struct.iter_unpack('<III',table))
            nonzero = [row for row in entries if any(row)]
            image['unwind_table'] = {'entries':len(nonzero),'ranges_in_image':all(0<a<b<=image['image_size'] and 0<u<image['image_size'] for a,b,u in nonzero),
                                     'sorted_by_start':all(a[0]<=b[0] for a,b in zip(nonzero,nonzero[1:])),
                                     'scope':'PE table structure only; no actual recorded-stack unwind completeness proven.'}
    args.output.write_text(json.dumps(extended,indent=2)+'\n',encoding='utf-8')
    print('MATCHED',[(t['target_pid'],len(t['matched_records'])) for t in trials],'EXTRA',len(additions))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--traces',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())

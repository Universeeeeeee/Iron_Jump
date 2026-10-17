"""Offline DbgHelp symbol-name/address round trips; no stack recording/attach."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import uuid

from pe_identity import sha, pdb


class GUID(c.Structure):
    _fields_ = [('bytes', c.c_ubyte * 16)]


class MODULE(c.Structure):
    _fields_ = [('SizeOfStruct', w.DWORD), ('BaseOfImage', c.c_uint64),
        *[(k, w.DWORD) for k in ['ImageSize','TimeDateStamp','CheckSum','NumSyms','SymType']],
        ('ModuleName', c.c_char * 32), ('ImageName', c.c_char * 256), ('LoadedImageName', c.c_char * 256),
        ('LoadedPdbName', c.c_char * 256), ('CVSig', w.DWORD), ('CVData', c.c_char * 780),
        ('PdbSig', w.DWORD), ('PdbSig70', GUID),
        *[(k, w.DWORD) for k in ['PdbAge','PdbUnmatched','DbgUnmatched','LineNumbers','GlobalSymbols','TypeInfo','SourceIndexed','Publics','MachineType','Reserved']]]


class SYMBOL(c.Structure):
    _fields_ = [('SizeOfStruct',w.DWORD),('TypeIndex',w.DWORD),('Reserved',c.c_uint64*2),('Index',w.DWORD),
        ('Size',w.DWORD),('ModBase',c.c_uint64),('Flags',w.DWORD),('Value',c.c_uint64),('Address',c.c_uint64),
        *[(k,w.DWORD) for k in ['Register','Scope','Tag','NameLen','MaxNameLen']],('Name',c.c_char*1)]


class LINE(c.Structure):
    _fields_ = [('SizeOfStruct',w.DWORD),('Key',c.c_void_p),('LineNumber',w.DWORD),('FileName',c.c_char_p),('Address',c.c_uint64)]


def main(args):
    assert not args.output.exists()
    assert c.sizeof(MODULE) == 1680 and SYMBOL.Name.offset == 84 and c.sizeof(SYMBOL) == 88
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    process = kernel.GetCurrentProcess()
    dbgpath = Path('C:/Windows/System32/dbghelp.dll')
    dbg = c.WinDLL(str(dbgpath), use_last_error=True)
    dbg.SymInitializeW.argtypes = [w.HANDLE,w.LPCWSTR,w.BOOL]
    dbg.SymSetOptions.argtypes = [w.DWORD]
    dbg.SymSetOptions.restype = w.DWORD
    dbg.SymLoadModuleExW.argtypes = [w.HANDLE,w.HANDLE,w.LPCWSTR,w.LPCWSTR,c.c_uint64,w.DWORD,c.c_void_p,w.DWORD]
    dbg.SymLoadModuleExW.restype = c.c_uint64
    dbg.SymGetModuleInfo64.argtypes = [w.HANDLE,c.c_uint64,c.POINTER(MODULE)]
    dbg.SymFromAddr.argtypes = [w.HANDLE,c.c_uint64,c.POINTER(c.c_uint64),c.POINTER(SYMBOL)]
    dbg.SymGetLineFromAddr64.argtypes = [w.HANDLE,c.c_uint64,c.POINTER(w.DWORD),c.POINTER(LINE)]
    dbg.SymUnloadModule64.argtypes = [w.HANDLE,c.c_uint64]
    dbg.SymCleanup.argtypes = [w.HANDLE]
    callback_type = c.WINFUNCTYPE(w.BOOL,c.POINTER(SYMBOL),w.ULONG,c.c_void_p)
    dbg.SymEnumSymbols.argtypes = [w.HANDLE,c.c_uint64,c.c_char_p,callback_type,c.c_void_p]
    # Exact matches only; no LOAD_ANYTHING and no symbol-server network side effect.
    options = dbg.SymSetOptions(0x2 | 0x10 | 0x200 | (0 if args.export_fallback else 0x400) | 0x80000)
    search = ';'.join(str(p) for p in args.symbols)
    assert dbg.SymInitializeW(process, search, False), c.get_last_error()
    inventory = json.loads(args.inventory.read_text())
    names = ['python311.dll','Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll','QtCore.pyd','pyside6.abi3.dll',
             '_multiarray_umath.cp311-win_amd64.pyd','ntdll.dll','KERNELBASE.dll','libdev.dll','tinyse_capture_v2.dll','CyUsbInterface.dll','cv2.pyd','libmediapipe.dll']
    results = []
    try:
        for index, image in enumerate(v for v in inventory['images'] if Path(v['path']).name.lower() in {n.lower() for n in names}):
            base = 0x10000000000 + index * 0x100000000
            loaded = dbg.SymLoadModuleExW(process, None, image['path'], 'audit'+str(index), base, image['image_size'], None, 0)
            record = {'path': image['path'], 'image_sha256': sha(image['path']), 'loaded_base': loaded, 'load_error': c.get_last_error() if not loaded else 0, 'symbols': [], 'function_symbol_count': 0, 'function_examples': []}
            if loaded:
                def collect(pointer, size, context):
                    symbol = pointer.contents
                    name = c.string_at(c.addressof(symbol)+SYMBOL.Name.offset,symbol.NameLen).decode('utf-8',errors='replace')
                    # Select diagnostic families; bounded samples per family below.
                    if symbol.Tag == 5:
                        record['function_symbol_count'] += 1
                        if len(record['function_examples']) < 12:
                            record['function_examples'].append(name)
                    low = name.lower()
                    wanted = any(s in low for s in ['take_gil','drop_gil','restorethread','savethread','gilstate','acquire_lock','evalframedefault',
                                'qwaitcondition','qmutex','qbasicmutex','qthread::exec','waitforsingle','waitformultiple','sleepcondition','waitonaddress',
                                'ntwait','_multiarray','numpy','obsbot','dev::','tinyse_capture','cyread','bulk','readusb','getdevice','getbeam','mediapipe','tflite','xnn','pyarray','pyufunc','readusb','getusb','xfer','bulk','libdev','mutex'])
                    if wanted:
                        record['symbols'].append({'name': name,'address':symbol.Address,'rva':symbol.Address-base,'size':symbol.Size,'flags':symbol.Flags,'tag':symbol.Tag})
                    return True
                callback = callback_type(collect)
                record['enum_success'] = bool(dbg.SymEnumSymbols(process,base,b'*',callback,None))
                info = MODULE(); info.SizeOfStruct = c.sizeof(info)
                record['module_info_success'] = bool(dbg.SymGetModuleInfo64(process,base,c.byref(info)))
                record.update({key: int(getattr(info,key)) for key in ['SymType','PdbAge','PdbUnmatched','DbgUnmatched','LineNumbers','GlobalSymbols','Publics']})
                record['loaded_pdb'] = bytes(info.LoadedPdbName).decode(errors='replace')
                record['loaded_guid'] = str(uuid.UUID(bytes_le=bytes(info.PdbSig70.bytes))).upper()
                if record['loaded_pdb'] and Path(record['loaded_pdb']).exists():
                    record['pdb_identity_independent'] = pdb(record['loaded_pdb'])
                for symbol in record['symbols']:
                    buffer = c.create_string_buffer(c.sizeof(SYMBOL)+2048)
                    data = c.cast(buffer,c.POINTER(SYMBOL))
                    data.contents.SizeOfStruct = c.sizeof(SYMBOL); data.contents.MaxNameLen = 2048
                    displacement = c.c_uint64()
                    success = dbg.SymFromAddr(process,symbol['address'],c.byref(displacement),data)
                    symbol['roundtrip_name'] = c.string_at(c.addressof(data.contents)+SYMBOL.Name.offset,data.contents.NameLen).decode(errors='replace') if success else None
                    symbol['roundtrip_displacement'] = displacement.value if success else None
                    if symbol['tag'] == 5 and symbol['size'] > 16:
                        offset = c.c_uint64()
                        if dbg.SymFromAddr(process,symbol['address']+16,c.byref(offset),data):
                            symbol['interior_roundtrip'] = {'name':c.string_at(c.addressof(data.contents)+SYMBOL.Name.offset,data.contents.NameLen).decode(errors='replace'),'displacement':offset.value}
                    line = LINE();line.SizeOfStruct = c.sizeof(line); delta = w.DWORD()
                    if dbg.SymGetLineFromAddr64(process,symbol['address'],c.byref(delta),c.byref(line)):
                        symbol['source'] = {'file':line.FileName.decode(errors='replace'),'line':line.LineNumber,'displacement':delta.value}
                dbg.SymUnloadModule64(process,base)
            results.append(record)
    finally:
        dbg.SymCleanup(process)
    value = {'scope':'Offline DbgHelp load of image metadata only; no process invasion, target DLL LoadLibrary, sampling, waits or capture.',
             'dbghelp_path':str(dbgpath),'dbghelp_sha256':sha(dbgpath),'options':hex(options),'search_path':search,
             'script_sha256':sha(Path(__file__)),'modules':results}
    args.output.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print([(Path(v['path']).name,v.get('SymType'),v.get('loaded_pdb'),len(v['symbols'])) for v in results])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--symbols',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--export-fallback',action='store_true')
    main(p.parse_args())

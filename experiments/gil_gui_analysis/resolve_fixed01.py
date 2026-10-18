"""Offline static exact-image/PDB resolution of preserved native addresses; no target attach."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import uuid


def main(args):
    sys.path.insert(0,str(args.preflight));from pe_identity import pe,pdb,sha;from resolve import MODULE,SYMBOL
    rows=[json.loads(s) for s in args.samples.read_text().splitlines()];modules={}
    for row in rows:
        for native in row.get('native',[]):
            for f in native['frames']:
                assert f['module_base']>0 and f['module_offset']==f['address']-f['module_base']
                name=f['symbol']['module'];key=f['module_base']
                if key in modules:assert modules[key]['path']==name
                else:modules[key]=dict(base=key,path=name,addresses=set())
                modules[key]['addresses'].add(f['address'])
    k=C.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=W.HANDLE;process=k.GetCurrentProcess()
    dbg=C.WinDLL('C:/Windows/System32/dbghelp.dll',use_last_error=True)
    dbg.SymInitializeW.argtypes=[W.HANDLE,W.LPCWSTR,W.BOOL]
    dbg.SymLoadModuleExW.argtypes=[W.HANDLE,W.HANDLE,W.LPCWSTR,W.LPCWSTR,C.c_uint64,W.DWORD,C.c_void_p,W.DWORD];dbg.SymLoadModuleExW.restype=C.c_uint64
    dbg.SymGetModuleInfo64.argtypes=[W.HANDLE,C.c_uint64,C.POINTER(MODULE)]
    dbg.SymFromAddr.argtypes=[W.HANDLE,C.c_uint64,C.POINTER(C.c_uint64),C.POINTER(SYMBOL)]
    dbg.SymCleanup.argtypes=[W.HANDLE];dbg.SymSetOptions(0x80612)
    assert dbg.SymInitializeW(process,str(args.preflight/'symbols')+';'+str(args.preflight/'symbols/vendor'),False)
    results=[]
    try:
        for slot,m in enumerate(modules.values()):
            image=pe(m['path']);m['image_sha256']=image['sha256'];m['image_size']=image['image_size'];m['codeview']=image['codeview'];m['pdb_matched']=False
            lookup_base=0x10000000000+slot*0x100000000
            base=dbg.SymLoadModuleExW(process,None,str(Path(m['path'])),None,lookup_base,image['image_size'],None,0)
            assert base==lookup_base,(m['path'],lookup_base,base,C.get_last_error())
            m['lookup_base']=lookup_base
            info=MODULE();info.SizeOfStruct=C.sizeof(info);assert dbg.SymGetModuleInfo64(process,base,C.byref(info))
            assert info.BaseOfImage==base and info.ImageSize==image['image_size']
            m['sym_type']=info.SymType;m['loaded_pdb']=bytes(info.LoadedPdbName).decode(errors='replace');m['pdb_unmatched']=bool(info.PdbUnmatched)
            if info.SymType==3 and m['loaded_pdb']:
                identity=pdb(m['loaded_pdb']);m['pdb_identity']=identity
                loaded_guid=str(uuid.UUID(bytes_le=bytes(info.PdbSig70.bytes))).upper()
                m['loaded_guid']=loaded_guid;m['loaded_age']=info.PdbAge
                m['pdb_matched']=not info.PdbUnmatched and any(cv['guid']==identity['guid']==loaded_guid and cv['age']==identity['age']==info.PdbAge for cv in image['codeview'])
            resolved=[]
            for address in sorted(m.pop('addresses')):
                r=dict(address=address,module_base=m['base'],module_offset=address-m['base'],symbol=None,pdb_matched=m['pdb_matched'])
                if m['pdb_matched']:
                    buffer=C.create_string_buffer(C.sizeof(SYMBOL)+2048);symbol=C.cast(buffer,C.POINTER(SYMBOL));symbol.contents.SizeOfStruct=C.sizeof(SYMBOL);symbol.contents.MaxNameLen=2048;delta=C.c_uint64()
                    if dbg.SymFromAddr(process,lookup_base+address-m['base'],C.byref(delta),symbol):r.update(symbol=C.string_at(C.addressof(symbol.contents)+SYMBOL.Name.offset,symbol.contents.NameLen).decode(errors='replace'),displacement=delta.value)
                resolved.append(r)
            m['resolved']=resolved;results.append(m)
    finally:dbg.SymCleanup(process)
    with args.output.open('x') as out:json.dump(dict(samples_sha256=sha(args.samples),resolver_sha256=sha(Path(__file__)),identity_helpers_sha256={n:sha(args.preflight/n) for n in ('pe_identity.py','resolve.py')},dbghelp_sha256=sha(Path('C:/Windows/System32/dbghelp.dll')),scope='Static image/PDB lookup after fixed GUI replay exit. In-sample symbol strings are not used as proof; unmatched frames keep original module+RVA.',modules=results),out,indent=2)
    print(json.dumps([dict(path=m['path'],pdb_matched=m['pdb_matched'],addresses=len(m['resolved'])) for m in results]))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--samples',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--preflight',type=Path,required=True);main(p.parse_args())

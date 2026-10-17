"""Resolve delivered ETW addresses with exact cached PDBs; retain module+RVA on gaps."""
import argparse
import base64
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import struct
import sys
import uuid


def main(a):
    sys.path.insert(0, str(a.preflight))
    from pe_identity import pe, pdb, sha
    from resolve import MODULE, SYMBOL
    if a.output.exists():
        raise FileExistsError(a.output)
    events = [json.loads(line) for line in a.events.read_text().splitlines()]
    modules, addresses = {}, set()
    for e in events:
        data = base64.b64decode(e['payload'])
        if e['provider'].startswith('2cb15d1d') and e['opcode'] in (3, 4, 10):
            base, size, pid, checksum = struct.unpack_from('<QQII', data)
            name = data[56:].decode('utf-16le').split('\0')[0]
            modules[(pid, base)] = dict(base=base, size=size, pid=pid, checksum=checksum, recorded_path=name)
        if e['provider'].startswith('def2fe46') and e['opcode'] == 32:
            addresses.update(struct.unpack_from('<' + 'Q' * ((len(data)-16)//8), data, 16))
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    process = kernel.GetCurrentProcess()
    dbg = c.WinDLL('C:/Windows/System32/dbghelp.dll', use_last_error=True)
    dbg.SymInitializeW.argtypes = [w.HANDLE, w.LPCWSTR, w.BOOL]
    dbg.SymLoadModuleExW.argtypes = [w.HANDLE,w.HANDLE,w.LPCWSTR,w.LPCWSTR,c.c_uint64,w.DWORD,c.c_void_p,w.DWORD]
    dbg.SymLoadModuleExW.restype = c.c_uint64
    dbg.SymGetModuleInfo64.argtypes = [w.HANDLE,c.c_uint64,c.POINTER(MODULE)]
    dbg.SymFromAddr.argtypes = [w.HANDLE,c.c_uint64,c.POINTER(c.c_uint64),c.POINTER(SYMBOL)]
    dbg.SymCleanup.argtypes = [w.HANDLE]
    dbg.SymSetOptions(0x2 | 0x10 | 0x200 | 0x400 | 0x80000)
    search = str(a.preflight/'symbols') + ';' + str(a.preflight/'symbols/vendor')
    if not dbg.SymInitializeW(process, search, False):
        raise c.WinError(c.get_last_error())
    devices = {}
    kernel.QueryDosDeviceW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        buffer = c.create_unicode_buffer(32768)
        if kernel.QueryDosDeviceW(letter + ':', buffer, len(buffer)):
            devices[buffer.value.lower()] = letter + ':'
    seen_bases = set()
    try:
        for m in modules.values():
            name = m['recorded_path']
            if name.startswith('\\??\\'): name = name[4:]
            if name.lower().startswith('\\systemroot\\'): name = 'C:/Windows/' + name[12:]
            for device, drive in devices.items():
                if name.lower().startswith(device + '\\'):
                    name = drive + name[len(device):]
                    break
            path = Path(name)
            m['pdb_matched'] = False
            if not path.is_file():
                m['reason'] = 'Recorded file unavailable; no basename substitution'
                continue
            image = pe(path)
            m.update(path=str(path), sha256=image['sha256'], codeview=image['codeview'])
            if image['image_size'] != m['size'] or image['checksum'] != m['checksum']:
                m['reason'] = 'Image size/checksum mismatch'
                continue
            if m['base'] in seen_bases: continue
            seen_bases.add(m['base'])
            loaded = dbg.SymLoadModuleExW(process,None,str(path),None,m['base'],m['size'],None,0)
            if not loaded:
                m['reason'] = 'DbgHelp load failed'
                continue
            info = MODULE(); info.SizeOfStruct = c.sizeof(info)
            if not dbg.SymGetModuleInfo64(process, loaded, c.byref(info)):
                m['reason'] = 'Module info unavailable'
                continue
            m.update(sym_type=info.SymType, pdb_unmatched=bool(info.PdbUnmatched),
                     loaded_guid=str(uuid.UUID(bytes_le=bytes(info.PdbSig70.bytes))).upper(), loaded_age=info.PdbAge,
                     loaded_pdb=bytes(info.LoadedPdbName).decode(errors='replace'))
            if info.SymType == 3 and m['loaded_pdb']:
                identity = pdb(m['loaded_pdb'])
                m['pdb_identity'] = identity
                m['pdb_matched'] = (not info.PdbUnmatched and any(
                    cv['guid'] == identity['guid'] == m['loaded_guid'] and
                    cv['age'] == identity['age'] == m['loaded_age'] for cv in image['codeview']))
        resolved = {}
        for address in sorted(addresses):
            candidates = [m for m in modules.values() if m['base'] <= address < m['base']+m['size']]
            m = candidates[0] if len(candidates) == 1 else None
            r = dict(address=address, module=None, rva=None, symbol=None)
            if m:
                r.update(module=Path(m['recorded_path']).name, rva=address-m['base'], pdb_matched=m['pdb_matched'])
                if m['pdb_matched']:
                    buffer = c.create_string_buffer(c.sizeof(SYMBOL)+2048)
                    symbol = c.cast(buffer,c.POINTER(SYMBOL))
                    symbol.contents.SizeOfStruct=c.sizeof(SYMBOL); symbol.contents.MaxNameLen=2048
                    delta=c.c_uint64()
                    if dbg.SymFromAddr(process,address,c.byref(delta),symbol):
                        r.update(symbol=c.string_at(c.addressof(symbol.contents)+SYMBOL.Name.offset,symbol.contents.NameLen).decode(errors='replace'), displacement=delta.value)
            resolved[str(address)] = r
    finally:
        dbg.SymCleanup(process)
    a.output.write_text(json.dumps(dict(events_sha256=sha(a.events), device_map=devices, modules=list(modules.values()), addresses=resolved),indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('events',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--preflight',type=Path,default=Path('E:/OptoJump/IronJump-native-symbol-preflight-20261017-01'))
    main(p.parse_args())

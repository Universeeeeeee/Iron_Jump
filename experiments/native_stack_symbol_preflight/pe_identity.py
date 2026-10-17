"""Read-only PE/RSDS and MSF7-PDB identities. No target DLL execution."""
import hashlib
from pathlib import Path
import struct
import uuid


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pe(path):
    data = Path(path).read_bytes()
    assert data[:2] == b'MZ'
    header = struct.unpack_from('<I', data, 60)[0]
    assert data[header:header + 4] == b'PE\0\0'
    machine, count, stamp = struct.unpack_from('<HHI', data, header + 4)
    size = struct.unpack_from('<H', data, header + 20)[0]
    optional = header + 24
    magic = struct.unpack_from('<H', data, optional)[0]
    assert magic in (0x10b, 0x20b)
    directories = optional + (112 if magic == 0x20b else 96)
    sections = []
    for n in range(count):
        offset = optional + size + n * 40
        name = data[offset:offset + 8].rstrip(b'\0').decode('ascii', errors='replace')
        virtual_size, rva, raw_size, raw = struct.unpack_from('<IIII', data, offset + 8)
        sections.append({'name': name, 'rva': rva, 'virtual_size': virtual_size, 'raw_size': raw_size, 'raw_offset': raw})
    def offset(rva):
        if rva < struct.unpack_from('<I', data, optional + 60)[0]:
            return rva
        for section in sections:
            if section['rva'] <= rva < section['rva'] + max(section['virtual_size'], section['raw_size']):
                return section['raw_offset'] + rva - section['rva']
        raise ValueError(('RVA outside sections', hex(rva)))
    def text(rva):
        begin = offset(rva)
        return data[begin:data.index(b'\0', begin)].decode('utf-8', errors='replace')
    result = {'path': str(path), 'sha256': sha(path), 'bytes': len(data), 'machine': hex(machine),
              'timestamp': stamp, 'image_size': struct.unpack_from('<I', data, optional + 56)[0],
              'checksum': struct.unpack_from('<I', data, optional + 64)[0], 'sections': sections, 'codeview': [], 'exports': []}
    debug_rva, debug_size = struct.unpack_from('<II', data, directories + 6 * 8)
    if debug_rva:
        for n in range(debug_size // 28):
            entry = offset(debug_rva) + n * 28
            kind, length, address, pointer = struct.unpack_from('<IIII', data, entry + 12)
            if kind == 2 and data[pointer:pointer + 4] == b'RSDS':
                guid = str(uuid.UUID(bytes_le=data[pointer + 4:pointer + 20])).upper()
                age = struct.unpack_from('<I', data, pointer + 20)[0]
                name = data[pointer + 24:pointer + length].split(b'\0')[0].decode('utf-8', errors='replace')
                result['codeview'].append({'guid': guid, 'age': age, 'pdb_path': name,
                                           'symbol_key': guid.replace('-', '') + format(age, 'X')})
    export_rva, _ = struct.unpack_from('<II', data, directories)
    if export_rva:
        entry = offset(export_rva)
        base, nfunc, nname, functions, names, ordinals = struct.unpack_from('<IIIIII', data, entry + 16)
        for n in range(nname):
            nrva = struct.unpack_from('<I', data, offset(names) + n * 4)[0]
            ordinal = struct.unpack_from('<H', data, offset(ordinals) + n * 2)[0]
            frva = struct.unpack_from('<I', data, offset(functions) + ordinal * 4)[0]
            result['exports'].append({'name': text(nrva), 'rva': frva})
    return result


def pdb(path):
    data = Path(path).read_bytes()
    assert data[:32] == b'Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0', 'Not MSF7 PDB'
    block_size, _, blocks, directory_bytes, _, block_map = struct.unpack_from('<6I', data, 32)
    assert blocks * block_size <= len(data)
    count = (directory_bytes + block_size - 1) // block_size
    pages = struct.unpack_from('<' + 'I' * count, data, block_map * block_size)
    directory = b''.join(data[p * block_size:(p + 1) * block_size] for p in pages)[:directory_bytes]
    streams = struct.unpack_from('<I', directory)[0]
    sizes = struct.unpack_from('<' + 'I' * streams, directory, 4)
    cursor, contents = 4 + streams * 4, []
    for size in sizes:
        pages = 0 if size == 0xffffffff else (size + block_size - 1) // block_size
        ids = struct.unpack_from('<' + 'I' * pages, directory, cursor)
        cursor += pages * 4
        contents.append(b''.join(data[p * block_size:(p + 1) * block_size] for p in ids)[:size])
    version, signature, age = struct.unpack_from('<III', contents[1])
    dbi_signature, dbi_version, dbi_age = struct.unpack_from('<iII', contents[3])
    assert dbi_signature == -1
    return {'path': str(path), 'sha256': sha(path), 'bytes': len(data), 'guid': str(uuid.UUID(bytes_le=contents[1][12:28])).upper(),
            'age': dbi_age, 'info_age': age, 'age_source': 'DBI header (not Info-stream rewrite age)',
            'info_version': version, 'dbi_version': dbi_version, 'stream_count': streams}

"""Preserve tracerpt schema errors; compare raw lifecycle bytes, never invent fields."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

if __name__=='__main__':
    source=Path(sys.argv[1]);pid=int(sys.argv[2]);output=Path(sys.argv[3]);rows=[];errors=0
    for _,e in ET.iterparse(source,events=('end',)):
        if e.tag.split('}')[-1]!='Event':continue
        guid=e.find('.//{*}EventGuid');opcode=e.find('./{*}System/{*}Opcode')
        if guid is not None and guid.text.lower()=='{3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c}' and int(opcode.text) in (1,2,3,4):
            payload=e.find('.//{*}EventPayload');error=e.find('.//{*}ErrorCode')
            if error is not None:errors+=1
            if payload is not None:
                raw=bytes.fromhex(payload.text)
                if len(raw)>=8 and struct.unpack_from('<I',raw)[0]==pid:
                    rows.append(dict(opcode=int(opcode.text),version=int(e.find('./{*}System/{*}Version').text),pid=pid,tid=struct.unpack_from('<I',raw,4)[0],payload_hex=raw.hex(),schema_error=None if error is None else int(error.text),time_text=e.find('./{*}System/{*}TimeCreated').get('SystemTime')))
        e.clear()
    with output.open('x') as f:json.dump(dict(target_pid=pid,thread_schema_errors=errors,selected=rows,xml_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),named_start_address_decoded=False),f,indent=2)
    print(json.dumps(dict(selected=len(rows),thread_schema_errors=errors)))

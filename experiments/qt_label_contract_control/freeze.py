"""Freeze the compiled oracle and exact existing libraries before either call."""
import hashlib
import json
from pathlib import Path
import struct

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    modules={
        'D:/conda/python311.dll':'162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00',
        'D:/conda/Lib/site-packages/PySide6/Qt6Core.dll':'65fe6224b6c47a15b058738031d31dce9928c4d7a58e1b8db6434f6f5cddd702',
        'D:/conda/Lib/site-packages/PySide6/Qt6Widgets.dll':'5a9f37dedd3dc5bcc1a4bb8ea919c49fc62df751a1450accc34379eb6710eab6',
        'D:/conda/Lib/site-packages/PySide6/QtWidgets.pyd':'85cb6c2181b4b09887a7d8507dd950844d1b8f74a9c4002c7b71169f75bf6fda',
        'D:/conda/Lib/site-packages/shiboken6/shiboken6.abi3.dll':'47f4f9b44c95037565dd14f4be04f350f20c53c05483b750e0be867c39a7441e'}
    assert all(sha(Path(p))==v for p,v in modules.items())
    d=Path('D:/conda/Lib/site-packages/PySide6/Qt6Core.dll').read_bytes()
    pe=struct.unpack_from('<I',d,60)[0];opt=pe+24
    assert d[pe:pe+4]==b'PE\0\0' and struct.unpack_from('<H',d,pe+4)[0]==0x8664
    n=struct.unpack_from('<H',d,pe+6)[0];size=struct.unpack_from('<H',d,pe+20)[0];sections=[]
    for i in range(n):
        v,at,rawsize,raw=struct.unpack_from('<IIII',d,opt+size+40*i+8);sections.append((at,rawsize,raw))
    def offset(rva):
        found=[raw+rva-at for at,size,raw in sections if at<=rva<at+size];assert len(found)==1;return found[0]
    rva=struct.unpack_from('<I',d,opt+112)[0];e=struct.unpack_from('<IIHHIIIIIII',d,offset(rva));names=e[7];pointers=e[9]
    matching=[]
    for i in range(names):
        at=offset(struct.unpack_from('<I',d,offset(pointers)+4*i)[0]);name=d[at:d.index(b'\0',at)].decode()
        if 'qInstallMessageHandler' in name:matching.append(name)
    assert len(matching)==1
    sources={n:sha(HERE/n) for n in ('MessageOracle.c','build.cmd','check.py','control.py','freeze.py','test_check.py')}
    plan=dict(base_commit='375773994248f4ec076af5a0bceb380051c35bd4',scope='Synthetic GIL contract control only; two invalid-paint calls, no image or performance endpoint.',
        call_order=['binding_protected_base','direct_same_native_export'],retry_budget=0,process_budget=1,
        maximum_native_messages=32,expected_message_type=1,expected_errors='Qt invalid-paint warnings are deliberately generated in both calls.',
        sources=sources,dll_sha256=sha(HERE/'MessageOracle.dll'),exact_modules=modules,qInstallMessageHandler_export=matching[0],
        old_acceptance_upgraded=False,field_attribution_ready=False,performance_AB=False,formal_change_authorized=False)
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    print(json.dumps(plan,indent=2))

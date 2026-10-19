"""Exact-image-size check for the prior public C-API pointer observation."""
import hashlib,json,struct,sys
from pathlib import Path
if __name__=='__main__':
    result=json.loads(Path(sys.argv[1]).read_text());p=Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd');data=p.read_bytes()
    assert hashlib.sha256(data).hexdigest()==result['numpy_pyd_sha256']
    header=struct.unpack_from('<I',data,0x3c)[0];opt=header+24;assert data[header:header+4]==b'PE\0\0' and struct.unpack_from('<H',data,opt)[0]==0x20b
    image_size=struct.unpack_from('<I',data,opt+56)[0];rva=result['constructor_numpy_rva'];assert 0<=rva<image_size
    sections=[];count=struct.unpack_from('<H',data,header+6)[0];optional=struct.unpack_from('<H',data,header+20)[0]
    for i in range(count):
        s=opt+optional+40*i;name=data[s:s+8].rstrip(b'\0').decode();vs,va,rs,raw=struct.unpack_from('<IIII',data,s+8);flags=struct.unpack_from('<I',data,s+36)[0]
        if va<=rva<va+vs:sections.append(dict(name=name,rva=va,virtual_size=vs,executable=bool(flags&0x20000000)))
    assert len(sections)==1 and sections[0]['executable']
    output=dict(exact_numpy_image_size=image_size,constructor_rva=rva,constructor_inside_exact_executable_section=sections[0],approximate_file_size_bound_not_used_as_proof=True,
        original_read_sha256=hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),new_capture=False)
    with Path(sys.argv[2]).open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(output))

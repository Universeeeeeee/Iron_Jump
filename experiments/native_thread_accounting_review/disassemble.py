"""Read exact PE unwind ranges at witnessed IPs; do not execute or invent symbols."""
import hashlib,json,re,struct,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def pe(data):
    pos=struct.unpack_from('<I',data,0x3c)[0];assert data[:2]==b'MZ' and data[pos:pos+4]==b'PE\0\0'
    machine,count=struct.unpack_from('<HH',data,pos+4);size=struct.unpack_from('<H',data,pos+20)[0];opt=pos+24
    assert machine==0x8664 and struct.unpack_from('<H',data,opt)[0]==0x20b
    base=struct.unpack_from('<Q',data,opt+24)[0];sections=[]
    for i in range(count):
        p=opt+size+i*40;vs,rva,rs,raw=struct.unpack_from('<IIII',data,p+8);sections.append((rva,max(vs,rs),raw,rs))
    def offset(rva):
        rows=[s for s in sections if s[0]<=rva<s[0]+s[3]];assert len(rows)==1
        s=rows[0];return s[2]+rva-s[0]
    rva,size=struct.unpack_from('<II',data,opt+112+3*8);assert size%12==0
    table=[struct.unpack_from('<III',data,offset(rva)+i) for i in range(0,size,12)]
    return base,offset,table
if __name__=='__main__':
    identity=json.loads((HERE/'binary_identity01.json').read_text());binary=HERE/'runs/libmediapipe.dll';assert sha(binary)==identity['sha256']
    data=binary.read_bytes();base,offset,table=pe(data);samples=json.loads((HERE/'expanded_cpu_review01.json').read_text());examples=[w for w in samples['individual_examples'] if w['ip']['module'].lower().endswith('libmediapipe.dll')]
    selected={w['ip']['rva']:w for w in examples};out=[]
    for rva,w in sorted(selected.items()):
        ranges=[(a,b,u) for a,b,u in table if a<=rva<b]
        row=dict(tid=w['tid'],qpc=w['qpc'],sample_rva=rva,pdb_function_name=None,module_sha256=identity['sha256'])
        if len(ranges)!=1:row['unwind_range_unknown']=True;out.append(row);continue
        begin,end,unwind=ranges[0];command=['/usr/bin/objdump','-d',f'--start-address={hex(base+begin)}',f'--stop-address={hex(base+end)}',str(binary)]
        result=subprocess.run(command,capture_output=True,text=True,check=True);text=result.stdout
        filename=f'libmediapipe_{rva:x}_disassembly.txt';path=HERE/'runs'/filename
        with path.open('x') as f:f.write(text)
        # Extract instruction records; nearest-export annotations remain raw but
        # are explicitly not accepted as the enclosing private function's name.
        lines=[]
        for line in text.splitlines():
            match=re.match(r'^([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)$',line)
            if match:lines.append(dict(rva=int(match.group(1),16)-base,bytes=match.group(2).strip(),instruction=match.group(3)))
        at=[v for v in lines if v['rva']==rva];assert len(at)==1,'Witness IP is not on a decoded instruction boundary'
        i=lines.index(at[0]);row.update(unwind_begin_rva=begin,unwind_end_rva=end,unwind_info_rva=unwind,
            witnessed_instruction=at[0],nearby_instructions=lines[max(0,i-4):i+5],
            range_vector_arithmetic_present=any(re.search(r'\bv(fmadd|mulps|addps|minps|maxps)',v['instruction']) for v in lines),
            range_pause_present=any(re.search(r'\bpause\b',v['instruction']) for v in lines),
            raw_disassembly_sha256=sha(path),disassembler_symbol_labels_not_used=True)
        out.append(row)
    result=dict(scope='ExactPE offline instruction/unwind-range review at retainedCPU witness IPs; no target execution.',module_sha256=identity['sha256'],examples=out,
        limits=['Nearest exported symbol plus displacement is not a private function identity.','Instruction evidence does not name convolution/GEMM/operator ormeasure cost share.','One witnessed vector arithmetic instruction does not exclude other waits/spins elsewhere orprove startup root cause.','Original failedCPUtrace and actual-load calibration remain failed.'],new_capture=False,primary_root_identified=False)
    with (HERE/'instruction_review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({hex(v['sample_rva']):v.get('witnessed_instruction') for v in out},indent=2))

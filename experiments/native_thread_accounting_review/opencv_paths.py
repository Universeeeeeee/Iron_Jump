"""Annotate retained CPU witnesses by exact public entries and instruction bytes."""
import hashlib,json,re,subprocess
from pathlib import Path
from disassemble import pe
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def public_entries(frames,entries):
    return sorted({entry['name'] for entry in entries if entry['unwind_range'] and any(f.get('module','').lower()=='cv2.pyd' and entry['unwind_range'][0]<=f['rva']<entry['unwind_range'][1] for f in frames)})
if __name__=='__main__':
    mapping=read(ROOT/'experiments/native_stack_capture/field_reviews/opencv_boundary01/entry_map01.json')
    assert mapping['script_sha256']==sha(ROOT/'experiments/native_stack_capture/field_reviews/opencv_boundary01/map_entries.py')
    binary=HERE/'runs/cv2.pyd';assert sha(binary)==mapping['sha256'];data=binary.read_bytes();base,offset,functions=pe(data)
    expanded=read(HERE/'expanded_cpu_review01.json');examples=[]
    for v in expanded['individual_examples']:
        if not v['ip']['module'].lower().endswith('cv2.pyd'):continue
        assert v['ip']['sha256']==mapping['sha256'];rva=v['ip']['rva'];ranges=[(a,b,u) for a,b,u in functions if a<=rva<b]
        row=dict(tid=v['tid'],qpc=v['qpc'],sample_rva=rva,public_caller_entries=public_entries(v['frames'],mapping['entries']),private_function_name=None)
        if len(ranges)!=1:row['instruction_range_unknown']=True;examples.append(row);continue
        begin,end,unwind=ranges[0];cmd=['/usr/bin/objdump','-d',f'--start-address={hex(base+begin)}',f'--stop-address={hex(base+end)}',str(binary)]
        output=subprocess.run(cmd,check=True,capture_output=True,text=True).stdout;name=HERE/'runs'/f'cv2_{rva:x}_disassembly.txt'
        with name.open('x') as f:f.write(output)
        records=[]
        for line in output.splitlines():
            m=re.match(r'^([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)$',line)
            if m:records.append(dict(rva=int(m.group(1),16)-base,bytes=m.group(2).strip(),instruction=m.group(3)))
        found=[x for x in records if x['rva']==rva];assert len(found)==1
        code=bytes.fromhex(found[0]['bytes']);assert data[offset(rva):offset(rva)+len(code)]==code
        i=records.index(found[0]);row.update(unwind_range=[begin,end],sample_instruction=found[0],nearby_instructions=records[max(0,i-4):i+5],disassembly_sha256=sha(name),nearest_export_label_ignored=True)
        examples.append(row)
    result=dict(target_pid=11948,scope='Old sameCPUtrace individual paths only, not CPUshares orstartup cause.',module_sha256=mapping['sha256'],examples=examples,
        interpretation=['A native worker can execute the same private range as a caller whose closed stack includes cv2.resize; this does not identify which simultaneous resize job supplied the worker.','Public entry ranges identify a boundary, not a unique Python business caller.','Vector instructions at anIP are computation/memory witnesses, not proof of a named OpenCV internal operator.','No-GIL/GILhold orwaiting duration cannot be inferred from module/entry/instruction names.'],new_capture=False,primary_root_identified=False,
        bindings=dict(expanded_cpu_review_sha256=sha(HERE/'expanded_cpu_review01.json'),entry_map_sha256=sha(ROOT/'experiments/native_stack_capture/field_reviews/opencv_boundary01/entry_map01.json'),script_sha256=sha(Path(__file__))))
    with (HERE/'opencv_paths01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps([{k:v.get(k) for k in ('tid','sample_rva','public_caller_entries','sample_instruction')} for v in examples],indent=2))

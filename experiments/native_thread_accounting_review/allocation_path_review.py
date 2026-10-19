"""Bind a retained GIL wait to an exact array-construction path, not CPU shares."""
import hashlib,json,re,subprocess
from pathlib import Path
from disassemble import pe
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    observation=read(HERE/'array_boundary01.json');validation=read(HERE/'array_identity_validation01.json');assert validation['original_read_sha256']==sha(HERE/'array_boundary01.json')
    data=(HERE/'runs/cv2.pyd').read_bytes();assert hashlib.sha256(data).hexdigest()==observation['cv2_sha256'];base,offset,table=pe(data)
    ranges=[(a,b,u) for a,b,u in table if a<=0x1ea260d<b];assert len(ranges)==1
    begin,end,unwind=ranges[0]
    cstring=lambda rva:data[offset(rva):data.index(b'\0',offset(rva))].decode('utf-8')
    assert cstring(0x5392f90)=='NumpyAllocator::allocate'
    assert cstring(0x5392f40).endswith('modules\\python\\src2\\cv2_numpy.cpp')
    # Exact compiler error branch: r8 = function, r9 = file, stack arg = line46.
    assert data[offset(0x1ea2852):offset(0x1ea2852)+8]==bytes.fromhex('c74424202e000000')
    for at,opcode,target in ((0x1ea285a,b'\x4c\x8d\x0d',0x5392f40),(0x1ea2861,b'\x4c\x8d\x05',0x5392f90)):
        code=data[offset(at):offset(at)+7];assert code[:3]==opcode and at+7+__import__('struct').unpack_from('<i',code,3)[0]==target
    assert data[offset(0x1ea268a):offset(0x1ea268a)+3]==bytes.fromhex('4533db') # xor r11d,r11d
    for at,code in ((0x1ea277c,'4c895c2440'),(0x1ea2781,'44895c2438'),(0x1ea2786,'44895c2430'),(0x1ea278b,'4c895c2428'),(0x1ea2790,'4c895c2420')):
        assert data[offset(at):offset(at)+len(bytes.fromhex(code))]==bytes.fromhex(code)
    output=subprocess.run(['/usr/bin/objdump','-d',f'--start-address={hex(base+begin)}',f'--stop-address={hex(base+end)}',str(HERE/'runs/cv2.pyd')],capture_output=True,text=True,check=True).stdout
    raw=HERE/'runs/numpy_allocator_range01.txt'
    with raw.open('x') as f:f.write(output)
    # Preserve the actual instructions establishing the no-intervening-call zero
    # register flow into the nine-argument public constructor, plus GIL endpoints.
    selected=[]
    for line in output.splitlines():
        m=re.match(r'^([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)$',line)
        if m:
            rva=int(m.group(1),16)-base
            if 0x1ea268a<=rva<=0x1ea27a7:selected.append(dict(rva=rva,bytes=m.group(2).strip(),instruction=m.group(3)))
    calls=[r for r in selected if r['instruction'].startswith('call')];assert [r['rva'] for r in calls]==[0x1ea27a7]
    old=ROOT/'experiments/native_stack_capture/field_reviews/opencv_boundary01/witnesses01.json';w=read(old);assert all(sha(ROOT/n)==v for n,v in w['input_sha256'].items())
    waits=[v for v in w['wait_examples'] if v['GIL_boundary']=='PyGILState_Ensure' and any(f['module']=='cv2.pyd' and f['rva']==0x1ea260d for f in v['frames'])]
    assert waits and all(any(f['symbol']=='take_gil' and f['pdb_matched'] for f in v['frames']) for v in waits)
    result=dict(scope='Existing field waits plus exactPE/compiler strings and current publicC-API identity. No newimage call/workload, performance effect orprivatePDB match.',
        module_sha256=observation['cv2_sha256'],unwind_range=[begin,end],observed_wait_return_rva=0x1ea260d,
        embedded_source_function='NumpyAllocator::allocate',embedded_source_file=cstring(0x5392f40),embedded_error_line=46,name_basis='Compiler error-call arguments inside this unique unwind function, not nearest export orPDB.',private_pdb_symbol=None,
        GIL_acquire_before_constructor=observation['GIL_import_targets']['PyGILState_Ensure'],GIL_release_after_constructor=observation['GIL_import_targets']['PyGILState_Release'],
        constructor=dict(public_C_API='PyArray_New',actual_table_equal_numpy_capsule=observation['table_equals_numpy_array_api'],slot=93,type_slot=2,array_type_equals_numpy_ndarray=observation['type_slot_equals_numpy_ndarray'],call_rva=0x1ea27a7,external_data_argument=None,strides_argument=None,object_argument=None,internal_array_creation_path_confirmed=True),
        zero_argument_instruction_flow=selected,retained_field_wait_examples=waits,
        limits=['This is a waiter boundary, not identification of the GIL holder orallocation CPUcost.','No measured whole-window allocation count, GILhold duration, CPUshare orroot contribution.','No proof yet that a proposed dst/preallocation path removes this call while preserving concurrent lifetime and complete real work.','Model-open/serial CPU-state evidence is broader and cannot be explained solely by this one allocation boundary.','Old failed traces, actual-load3%/1% and original matrix remain unchanged.'],new_capture=False,primary_root_identified=False,field_fix_verified=False,
        bindings=dict(array_observation_sha256=sha(HERE/'array_boundary01.json'),exact_image_validation_sha256=sha(HERE/'array_identity_validation01.json'),original_waits_sha256=sha(old),disassembly_sha256=sha(raw),script_sha256=sha(Path(__file__))))
    with (HERE/'allocation_path01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(waiter_path=result['embedded_source_function'],constructor=result['constructor'],waits=[dict(pid=v['pid'],tid=v['tid'],public_entries=v['public_entry_names']) for v in waits]),indent=2))

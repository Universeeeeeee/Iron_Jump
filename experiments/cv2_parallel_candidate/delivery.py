"""Validate actual lifecycle delivery, not only the OpenCV configuration getter."""
import base64
import json
from pathlib import PureWindowsPath
import struct

def classify_starts(events,pid,begin_ns,end_ns,frequency,offset_low,offset_high,cv2_image):
    images=[];starts=[];unknown=[]
    for e in events:
        d=base64.b64decode(e['payload'])
        if e['provider'].startswith('2cb15d1d') and e['opcode']==10 and e['version'] in (2,3) and e['flags']&0x40 and len(d)>=58:
            base,size,owner,checksum=struct.unpack_from('<QQII',d)
            if owner==pid:images.append(dict(base=base,size=size,checksum=checksum,path=d[56:].decode('utf-16le').split('\0')[0],qpc=e['qpc']))
    for e in events:
        if not e['provider'].startswith('3d6fa8d1') or e['opcode']!=1:continue
        d=base64.b64decode(e['payload']);owner,tid=struct.unpack_from('<II',d)
        if owner!=pid:continue
        low=e['qpc']*10**9//frequency+offset_low;high=e['qpc']*10**9//frequency+offset_high
        if high<begin_ns or low>end_ns:continue
        if not begin_ns<=low<=high<=end_ns:
            unknown.append(dict(tid=tid,reason='start straddles work boundary'));continue
        if e['version']!=3 or not e['flags']&0x40 or len(d)!=74:
            unknown.append(dict(tid=tid,reason='unqualified layout'));continue
        address=struct.unpack_from('<Q',d,48)[0];matches=[m for m in images if m['qpc']<=e['qpc'] and m['base']<=address<m['base']+m['size']]
        if len(matches)!=1:
            unknown.append(dict(tid=tid,reason='unmapped or ambiguous entry'));continue
        m=matches[0]
        if PureWindowsPath(m['path']).name.lower()=='cv2.pyd':
            if m['size']!=cv2_image['image_size'] or m['checksum']!=cv2_image['checksum']:unknown.append(dict(tid=tid,reason='cv2 image mismatch'));continue
            starts.append(dict(tid=tid,qpc=e['qpc'],entry=address,module=m['path'],rva=address-m['base']))
    return dict(cv2_starts=starts,unknown=unknown)

def gate(default,one,pixels_default,pixels_one,count):
    return dict(default_cv2_workers_observed=bool(default['cv2_starts']),candidate_no_new_cv2_workers=not one['cv2_starts'],no_unclassified_starts=not default['unknown'] and not one['unknown'],exact_pixels=len(pixels_default)==len(pixels_one)==count and pixels_default==pixels_one)

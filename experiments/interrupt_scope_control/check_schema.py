"""Independent tracerpt/TDH fields, against preserved raw event bytes."""
import base64
import collections
import datetime
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
NS={'e':'http://schemas.microsoft.com/win/2004/08/events/event','t':'http://schemas.microsoft.com/win/2004/08/events/trace'}
PERF='ce1dbfb4-137e-4da6-87b0-3f59aa102cbc'
def check(root):
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    raw=collections.defaultdict(list);xml=collections.defaultdict(list)
    for line in (root/'decoded01/events.jsonl').read_text().splitlines():
        e=json.loads(line)
        if e['provider']==PERF and e['opcode'] in (50,66,67,68,69):raw[(e['cpu'],e['opcode'])].append(e)
    tree=ET.parse(root/'schema01.xml')
    for e in tree.getroot():
        guid=e.find('t:ExtendedTracingInfo/t:EventGuid',NS)
        if guid is None or guid.text.strip('{}').lower()!=PERF:continue
        opcode=int(e.find('e:System/e:Opcode',NS).text)
        if opcode not in (50,66,67,68,69):continue
        cpu=int(e.find('e:System/e:Execution',NS).attrib['ProcessorID'])
        fields={v.attrib['Name']:v.text.strip() for v in e.findall('e:EventData/e:Data',NS)}
        label=e.find('e:RenderingInfo/e:Opcode',NS)
        xml[(cpu,opcode)].append((fields,label.text,e.find('e:System/e:TimeCreated',NS).attrib['SystemTime']))
    assert set(raw)==set(xml)
    anchor=read(root/'target01.json')['before']['before'];freq=anchor['frequency'];proof=[];residual=[];timezone_tags=set()
    for key,events in raw.items():
        assert len(events)==len(xml[key])
        for e,(fields,label,formatted) in zip(events,xml[key]):
            data=base64.b64decode(e['payload']);op=e['opcode'];assert e['version']==2
            initial,routine=struct.unpack_from('<qQ',data)
            assert routine==int(fields['Routine'],0)
            if op==50:
                assert label=='ISR-MSI' and len(data)==24
                assert data[16]==int(fields['ReturnValue']) and data[17]==int(fields['Vector'])
                assert struct.unpack_from('<H',data,18)[0]==int(fields['Reserved'])
                assert struct.unpack_from('<I',data,20)[0]==int(fields['MessageNumber'])
            elif op==67:
                assert len(data)==20 and data[16]==int(fields['ReturnValue']) and data[17]==int(fields['Vector'])
            else:assert len(data)==16
            # tracerpt converts InitialTime toFILETIME; independent API anchor retains rawUTC/QPC bridge.
            expected=anchor['filetime_100ns']+(initial-(anchor['qpc_before']+anchor['qpc_after'])/2)*10000000/freq
            difference=int(fields['InitialTime'])-expected;residual.append(difference)
            assert abs(difference)<=10000,'Clock conversion not within1ms; do not use formatted timestamp'
            timezone_tags.add(formatted[-6:])
        proof.append(dict(cpu=key[0],opcode=key[1],count=len(events),labels=sorted({v[1] for v in xml[key]})))
    return dict(all_DPC_ISR_events_match_independent_TDH_fields=True,groups=proof,
        InitialTime_API_anchor_max_abs_residual_100ns=max(abs(v) for v in residual),
        rendered_timezone_tags=sorted(timezone_tags),formatted_TimeCreated_used_for_duration=False,
        ISR_MSI_opcode50_v2_length=24,ISR_opcode67_length=20,
        limitations=['tracerpt warned about other schemas; this proof covers only the independently matched DPC/ISR events.',
            'Formatted TimeCreated timezone tags are not used for duration; rawQPC andAPI anchors are checked.'])
if __name__=='__main__':
    h=Path(__file__).resolve().parent;out=check(h/'runs/evidence01')
    with (h/'schema_check01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))

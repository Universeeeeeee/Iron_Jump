"""Inspect Windows tracerpt schema independently of the project's payload offsets."""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

if __name__=='__main__':
    source=Path(sys.argv[1]);target=int(sys.argv[2]);output=Path(sys.argv[3]);rows=[];example=None;thread_events=0
    for event,end in ET.iterparse(source,events=('end',)):
        if end.tag.split('}')[-1]!='Event':continue
        provider=end.find('.//{*}Provider')
        if provider is not None and '3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c' in str(provider.attrib).lower():
            thread_events+=1
            if example is None:example=ET.tostring(end,encoding='unicode')
            values={x.get('Name'):x.text for x in end.findall('.//{*}Data')}
            pid=values.get('ProcessId')
            if pid is not None and int(pid,0)==target:rows.append(dict(properties=values,xml=ET.tostring(end,encoding='unicode')))
        end.clear()
    result=dict(target_pid=target,thread_events=thread_events,first_thread_schema=example,selected=rows,xml_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    with output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(thread_events=thread_events,selected=len(rows),first_thread_schema=example)))

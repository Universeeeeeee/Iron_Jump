from pathlib import Path
import sys
import xml.etree.ElementTree as ET
source=Path(sys.argv[1])
with source.open('rb') as f:print(repr(f.read(1000)))
count=0
for _,element in ET.iterparse(source,events=('end',)):
    if element.tag.split('}')[-1]=='Event':
        print(ET.tostring(element,encoding='unicode')[:2200]);count+=1;element.clear()
        if count==4:break

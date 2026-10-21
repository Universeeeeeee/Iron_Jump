"""Hash-checked local report handoff; IPC keeps its existing 8 MiB bound."""
import hashlib,json
MAX_REPORT_BYTES=64*1024*1024

def report_reference(folder):
 path=folder/'report.json';size=path.stat().st_size
 if not 0<size<=MAX_REPORT_BYTES:raise ValueError('Report file size outside bound')
 data=path.read_bytes()
 if len(data)!=size:raise ValueError('Report file changed during handoff')
 return dict(file='report.json',bytes=size,sha256=hashlib.sha256(data).hexdigest())

def read_report(folder,reference):
 if reference.get('file')!='report.json':raise ValueError('Unexpected report file')
 size=reference.get('bytes')
 if type(size) is not int or not 0<size<=MAX_REPORT_BYTES:raise ValueError('Report file size outside bound')
 path=folder/'report.json'
 if path.stat().st_size!=size:raise ValueError('Report file size mismatch')
 with path.open('rb') as source:data=source.read(size+1)
 if len(data)!=size or hashlib.sha256(data).hexdigest()!=reference.get('sha256'):raise ValueError('Report file hash/size mismatch')
 report=json.loads(data.decode('utf-8'))
 if not isinstance(report,dict):raise ValueError('Report must be an object')
 return report

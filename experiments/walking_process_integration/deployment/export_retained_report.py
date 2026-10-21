"""Write a derived v2 report/Excel without modifying the retained source report."""
import argparse,hashlib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('report',type=Path);p.add_argument('output',type=Path);a=p.parse_args();sys.path.insert(0,str(a.root))
from engine.footfall_records import footfall_records,FOOTFALL_SCHEMA,validate_footfalls
from data.subject_store import _report_from_detail,_report_detail
from reporting.excel import build_report_workbook
original=a.report.read_bytes();detail=json.loads(original);s=detail['walking_summary'];s['footfalls']=footfall_records(s);s['recognized_steps']=len(s['footfalls']);s['footfall_schema_version']=FOOTFALL_SCHEMA;validate_footfalls(s)
assert s['recognized_steps']==12 and s['valid_steps']==7 and s['valid_cycles']==4
report=_report_from_detail(dict(report_type='gait',report_schema_version=2,**detail));a.output.mkdir(parents=True,exist_ok=False);(a.output/'report_v2.json').write_text(json.dumps(_report_detail(report),ensure_ascii=False),encoding='utf-8');book=build_report_workbook(report)
assert book['Walking footfalls'].max_row==13 and book['Walking steps'].max_row==8 and book['Walking cycles'].max_row==5
book.save(a.output/'Walk-12-footfalls.xlsx');assert a.report.read_bytes()==original
result=dict(original_report_sha256=hashlib.sha256(original).hexdigest(),recognized_steps=12,footfall_rows=12,valid_step_relationships=7,cycles=4,source_report_unchanged=True,raw_exports_embedded=False,physical_devices_opened=False,derived_files={n:hashlib.sha256((a.output/n).read_bytes()).hexdigest() for n in ('report_v2.json','Walk-12-footfalls.xlsx')});(a.output/'manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

"""Inspect the current formal widgets with the retained report; no devices."""
import argparse,json,sys,hashlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from qtpy.QtWidgets import QApplication,QTextBrowser
from config.test_config import config_from_dict
from data.subject_store import _report_from_detail
from engine.footfall_records import footfall_records,FOOTFALL_SCHEMA
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.views.execution_view import ExecutionView
from ui.views.report_view import ReportView

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('report',type=Path);p.add_argument('output',type=Path);args=p.parse_args();original=json.loads(args.report.read_text(encoding='utf-8'));s=original['walking_summary'];s.update(footfall_schema_version=FOOTFALL_SCHEMA,footfalls=footfall_records(s));s['recognized_steps']=len(s['footfalls']);assert s['recognized_steps']==12 and s['valid_steps']==7 and s['valid_cycles']==4;report=_report_from_detail(dict(report_type='gait',report_schema_version=2,**original));app=QApplication([]);args.output.mkdir(parents=True,exist_ok=False)
 with patch.object(EmbeddedCameraPanel,'start_preview',side_effect=AssertionError('Hardware forbidden')):
  view=ExecutionView();view.resize(1400,820);view.configure(config_from_dict(original['report_config_snapshot']));view._camera_start_timer.stop();state=dict(original['visual_timeline'][-1],positions_m=original['report_config_snapshot']['device']['positions_m']);view._ground_track.render_state(state);view.on_gait_snapshot(dict(walking=s,touch_count=12,status='已完成',stride_count=0,velocity_count=0));view.show();app.processEvents();assert view._card_steps._title.text()=='识别步数' and view._card_steps._value.text()=='12';assert len(view._ground_track.channel.history)==12;assert view.grab().save(str(args.output/'execution.png'))
  details=ReportView();details.resize(1400,900);details.load_report(report);details.show();app.processEvents();text='\n'.join(browser.toPlainText() for browser in details.findChildren(QTextBrowser));assert '逐次落脚记录' in text;assert details.grab().save(str(args.output/'report.png'));result=dict(complete=True,recognized_card=12,footprint_history=12,footfall_table_rows=len(s['footfalls']),valid_steps=7,valid_cycles=4,source_report_sha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),physical_devices_opened=False);(args.output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));view.close();details.close()

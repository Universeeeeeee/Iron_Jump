"""One human passage, fresh child and unique evidence; owns only its WPR instance."""
import argparse,ctypes,hashlib,json,os,subprocess,sys,time,uuid
from datetime import datetime
from pathlib import Path
from protocol import read,write,mark
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
INSTANCE='IronJumpHumanSchedule'

def command(args,path):
    result=subprocess.run(args,capture_output=True,timeout=45)
    path.write_bytes(result.stdout+result.stderr)
    return result.returncode,(result.stdout+result.stderr).decode('utf-8-sig',errors='replace')

class Wpr:
    def __init__(self,root,enabled):self.root=root;self.enabled=enabled;self.owned=False;self.started=False;self.stop_count=0
    def start(self):
        code,status=command(['wpr.exe','-status'],self.root/'wpr_before.txt')
        if code!=0 or 'WPR is not recording' not in status:raise RuntimeError('已有或无法确认的 WPR 会话；不启动本轮，也不停止其他会话')
        if self.enabled:
            self.owned=True  # Reserve ownership before a possibly timed-out start.
            code,_=command(['wpr.exe','-start',str(HERE/'schedule.wprp')+'!IronJumpSchedule','-filemode','-instancename',INSTANCE],self.root/'wpr_start.txt')
            if code!=0:raise RuntimeError('ETW 启动失败，禁止正式采集')
            self.started=True
            code,status=command(['wpr.exe','-status','collectors','-details','-instancename',INSTANCE],self.root/'wpr_after_start.txt')
            if code!=0 or 'WPR_initiated_'+INSTANCE+'_' not in status:raise RuntimeError('本轮 ETW collector 未确认')
    def stop(self):
        if not self.owned:return
        self.stop_count+=1
        status_code,status=command(['wpr.exe','-status','collectors','-details','-instancename',INSTANCE],self.root/f'wpr_before_stop_{self.stop_count:02d}.txt')
        if 'WPR is not recording' in status:
            self.owned=False
            if self.started:raise RuntimeError('本轮 ETW 会话提前消失')
            return
        if status_code!=0 or 'WPR_initiated_'+INSTANCE+'_' not in status:raise RuntimeError('无法确认本轮 collector；保留锁，不触碰其他会话')
        code,_=command(['wpr.exe','-stop',str(self.root/'schedule.etl'),'-instancename',INSTANCE],self.root/f'wpr_stop_{self.stop_count:02d}.txt')
        if code!=0:raise RuntimeError('本轮 ETW 停止失败；保留锁和日志，请勿启动另一轮')
        self.owned=False
        if not (self.root/'schedule.etl').is_file() or (self.root/'schedule.etl').stat().st_size==0:raise RuntimeError('ETL 未落盘')
        mark(self.root,'trace_stopped',etl_bytes=(self.root/'schedule.etl').stat().st_size)

def check():
    if os.name!='nt':raise RuntimeError('请在 Windows 实验机启动')
    if not ctypes.windll.shell32.IsUserAnAdmin():raise RuntimeError('请使用桌面入口以管理员权限启动（WPR 需要）')
    for manifest,key in [(ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json','base_files'),(HERE/'frozen_sources.json','files')]:
        for name,digest in read(manifest)[key].items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('源码哈希不符: '+name)
    for name in ('drivers/CyUsbInterface.dll','camera/bin/tinyse_capture.dll','camera/bin/obsbot_c_api.dll','models/pose_landmarker_full.task'):
        if not (ROOT/name).is_file():raise RuntimeError('缺少实验依赖: '+name)
    dependencies=read(HERE/'dependencies.json')['files']
    for name,digest in dependencies.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('依赖哈希不符: '+name)
    from qtpy import QtCore
    if QtCore.qVersion() is None:raise RuntimeError('Qt 不可用')
    result=subprocess.run(['wpr.exe','-profiles',str(HERE/'schedule.wprp')],capture_output=True,timeout=15)
    if result.returncode!=0:raise RuntimeError('WPR profile 不可用')
    return {'checked_at':datetime.now().astimezone().isoformat(),'admin':True,'original_and_frozen_hashes_match':True,'wpr_profile_available':True,'dependency_files_verified':len(dependencies),'scope':'Static readiness only; no USB, SDK, camera or ETW recording started.'}

def capture(mode,trace):
    lock=HERE/'active.lock';lock.mkdir()  # Exclusive across all desktop entries; never auto-break stale locks.
    root=None;process=None;wpr=None;success=False;terminated=False;errors=[]
    try:
        run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        candidate=HERE/'runs'/f'{run_id}_{mode}_{trace}';candidate.mkdir(parents=True,exist_ok=False);root=candidate
        case={'run_id':run_id,'mode':mode,'trace':trace,'controller_pid':os.getpid(),'dependencies_sha256':hashlib.sha256((HERE/'dependencies.json').read_bytes()).hexdigest(),'frozen_sources_sha256':hashlib.sha256((HERE/'frozen_sources.json').read_bytes()).hexdigest()}
        write(root/'case.json',case);write(lock/'owner.json',{'controller_pid':os.getpid(),'evidence':str(root)})
        wpr=Wpr(root,trace=='on');out=root/'capture'
        with (root/'gui.log').open('xb') as log:
            process=subprocess.Popen([sys.executable,str(HERE/'entry.py'),'--output',str(out),'--mode',mode],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+540;started=False;stopped=False
            while time.monotonic()<deadline:
                request=root/'trace_request.json'
                if request.exists() and not started:
                    value=read(request)
                    if value['run_id']!=run_id or value['trace']!=trace:raise RuntimeError('请求不属于本轮')
                    wpr.start();started=True;mark(root,'trace_ready',run_id=run_id,trace=trace)
                if (root/'trace_end_request.json').exists() and not stopped:wpr.stop();stopped=True
                if (out/'complete.json').exists():
                    complete=read(out/'complete.json');shutdown=read(out/'shutdown.json')
                    success=complete=={'system_exit_code':0,'serialized':True} and shutdown['serialized'] and not shutdown['errors'] and not shutdown['SDK_errors'] and not shutdown['readers'] and shutdown['SDK']['stops']>0
                    if not success:raise RuntimeError('本轮取消、失败或 SDK/设备关闭未确认；保留全部证据')
                    break
                if process.poll() is not None:raise RuntimeError('实验窗口提前退出: '+str(process.returncode))
                time.sleep(.15)
            else:raise RuntimeError('外层 watchdog 超时')
    except BaseException as exc:
        errors.append(str(exc))
        if root is not None:mark(root,'abort_request',reason=str(exc))
    finally:
        if process is not None:
            try:
                try:process.wait(timeout=15 if not success else 3)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10);terminated=True
            except BaseException as exc:errors.append('child cleanup: '+str(exc));success=False
        try:
            if wpr is not None:wpr.stop()
        except BaseException as exc:errors.append(str(exc));success=False
        if root is not None:write(root/'controller_result.json',{'valid_capture':bool(success and not errors),'errors':errors,'terminated_after_child_cleanup':terminated,'child_returncode':None if process is None else process.returncode,'trace_owned_remaining':bool(wpr and wpr.owned),'scope':'Capture/cleanup status only. ETL event validation, under-load overhead, density and actual skeleton coverage remain offline decisions.'})
        if not (wpr and wpr.owned):
            if (lock/'owner.json').exists():(lock/'owner.json').unlink()
            lock.rmdir()
    print('证据目录:',root,flush=True)
    if errors:print('\n'.join(errors),flush=True)
    return 0 if success and not errors else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('walk','run'));p.add_argument('--trace',choices=('on','off'));p.add_argument('--check',action='store_true');a=p.parse_args()
    readiness=check()
    if a.check:print(json.dumps(readiness,ensure_ascii=False,indent=2))
    else:
        if not a.mode or not a.trace:p.error('--mode and --trace required')
        raise SystemExit(capture(a.mode,a.trace))

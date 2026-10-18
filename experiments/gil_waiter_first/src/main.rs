//! Requested thread first. No claim that a later owner caused the earlier wait.
use anyhow::{ensure, Context, Result};
use py_spy::{config::LockingStrategy, Config, PythonSpy};
use remoteprocess::{Process, Thread};
use serde_json::{json, Value};
use std::{fs::OpenOptions, io::{BufWriter, Write}, path::Path, thread, time::{Duration, Instant}};

#[link(name="kernel32")]
extern "system" {
    fn QueryPerformanceCounter(value: *mut i64) -> i32;
    fn QueryPerformanceFrequency(value: *mut i64) -> i32;
    fn ReadProcessMemory(process: *mut std::ffi::c_void, address: usize, buffer: *mut u64, size: usize, read: *mut usize) -> i32;
    fn OpenEventW(access: u32, inherit: i32, name: *const u16) -> *mut std::ffi::c_void;
    fn SetEvent(event: *mut std::ffi::c_void) -> i32;
    fn WaitForSingleObject(event: *mut std::ffi::c_void, timeout: u32) -> u32;
    fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
}
#[link(name="dbghelp")]
extern "system" { fn SymSetOptions(options: u32) -> u32; fn SymGetModuleBase64(process: *mut std::ffi::c_void, address: u64) -> u64; }

fn qpc() -> i64 { let mut n=0; assert_ne!(unsafe{QueryPerformanceCounter(&mut n)},0); n }
fn words(process: &Process, address: usize, count: usize) -> Result<Value> {
    if address==0 { return Ok(Value::Null); }
    let begin=qpc(); let mut values=vec![0u64;count]; let mut read=0;
    ensure!(unsafe{ReadProcessMemory(*process.handle,address,values.as_mut_ptr(),count*8,&mut read)}!=0 && read==count*8,"Remote read failed");
    Ok(json!({"qpc_begin":begin,"qpc_end":qpc(),"values":values}))
}

struct Event(*mut std::ffi::c_void);
impl Event {
    fn open(name: String) -> Result<Self> {
        let name: Vec<u16>=name.encode_utf16().chain(Some(0)).collect();
        let h=unsafe{OpenEventW(0x100002,0,name.as_ptr())};ensure!(!h.is_null(),"Synthetic event missing");Ok(Self(h))
    }
}
impl Drop for Event { fn drop(&mut self) { assert_ne!(unsafe{CloseHandle(self.0)},0); } }
struct TestGate { pre: Event, go: Event }
impl TestGate {
    fn checkpoint(&self) -> Result<()> {
        ensure!(unsafe{SetEvent(self.pre.0)}!=0,"Synthetic pre event failed");
        ensure!(unsafe{WaitForSingleObject(self.go.0,3000)}==0,"Synthetic transition timed out");Ok(())
    }
}

struct Native { tid:u32, ip:u64, sp:u64, bp:u64, addresses:Vec<u64>, stopped_by:&'static str }
fn unwind(unwinder:&remoteprocess::Unwinder,t:&Thread) -> Result<Native> {
    let mut c=unwinder.cursor(t).context("GetThreadContext failed")?;
    let (ip,sp,bp)=(c.ip(),c.sp(),c.bp());let mut addresses=vec![ip];
    let mut stopped_by="StackWalk64 returned false; closure must be checked independently";
    for _ in 0..255 {
        match c.next(){Some(a)=>addresses.push(a.context("Unwind error")?),None=>break}
        if addresses.len()==256{stopped_by="frame cap; incomplete";}
    }
    Ok(Native{tid:t.id()?,ip,sp,bp,addresses,stopped_by})
}

struct Sample {
    ordinal:u32, begin:i64, end:i64, request_call:i64, request_locked:i64,
    pre_begin:i64, pre_end:i64, global_call:i64, global_locked:i64, global_resumed:i64,
    pre_native:Native, native:Vec<Native>, traces:Vec<py_spy::StackTrace>, oracle:Vec<Value>, current:Vec<Value>,
}
fn snapshot(spy:&mut PythonSpy,process:&Process,unwinder:&remoteprocess::Unwinder,requested:&Thread,
            ordinal:u32,address:usize,test:&Option<TestGate>) -> Result<Sample> {
    let begin=qpc();let pre_oracle=words(process,address,4)?;
    let current0=words(process,spy.threadstate_address,1)?;
    // This exact retained Thread supplies both its lock and its native context.
    let request_call=qpc();let request_lock=requested.lock().context("Requested SuspendThread failed")?;
    let request_locked=qpc();let pre_begin=qpc();let pre_native=unwind(unwinder,requested)?;let pre_end=qpc();
    let current1=words(process,spy.threadstate_address,1)?;
    // Only synthetic tests may add a controlled transition while the requester
    // is frozen. It is absent from the normal path and cannot qualify overhead.
    if let Some(gate)=test {gate.checkpoint()?;}
    let global_call=qpc();let global=process.lock().context("NtSuspendProcess failed")?;let global_locked=qpc();
    let inner0=words(process,address,4)?;let current2=words(process,spy.threadstate_address,1)?;
    let traces=spy.get_stack_traces().context("Python read failed")?;
    ensure!(traces.iter().all(|t|t.pid==process.pid),"Python PID mismatch");
    let owners:Vec<_>=traces.iter().filter(|t|t.owns_gil).collect();ensure!(owners.len()<=1,"Multiple owners");
    let mut wanted=vec![requested.id()?];
    for t in owners {wanted.push(t.os_thread_id.context("No owner OS TID")?.try_into()?);}
    wanted.sort_unstable();wanted.dedup();
    let threads=process.threads()?;let mut native=Vec::new();
    for tid in wanted {
        let t=threads.iter().find(|t|t.id().ok()==Some(tid)).context("Native target missing")?;
        native.push(unwind(unwinder,t)?);
    }
    let inner1=words(process,address,4)?;
    // Release in reverse order. Failed Drop resume checks panic; no successful
    // sample is emitted. Requested context is frozen across both reads.
    drop(global);let global_resumed=qpc();drop(request_lock);let end=qpc();
    let post_oracle=words(process,address,4)?;
    Ok(Sample{ordinal,begin,end,request_call,request_locked,pre_begin,pre_end,global_call,global_locked,global_resumed,
        pre_native,native,traces,oracle:vec![pre_oracle,inner0,inner1,post_oracle],current:vec![current0,current1,current2]})
}

fn resolve(n:&Native,process:&Process,symbols:&remoteprocess::Symbolicator) -> Value {
    let mut frames=Vec::new();
    for address in &n.addresses {
        let base=unsafe{SymGetModuleBase64(*process.handle,*address)};let mut symbol=None;
        let r=symbols.symbolicate(*address,false,&mut |s|{symbol=Some(json!({"function":s.function,"module":s.module,"filename":s.filename,"line":s.line}));});
        frames.push(json!({"address":address,"module_base":base,"module_offset":if base>0 && *address>=base{Some(*address-base)}else{None},"symbol":symbol,"symbol_error":r.err().map(|e|format!("{e}")),"pdb_match_verified":false}));
    }
    json!({"tid":n.tid,"context_ip":n.ip,"context_sp":n.sp,"context_bp":n.bp,"frames":frames,"stopped_by":n.stopped_by})
}

fn main() -> Result<()> {
    let args:Vec<_>=std::env::args().collect();ensure!(args.len()==7,"usage: candidate PID REQUESTED_TID COUNT PERIOD_MS ORACLE_ADDRESS NEW_OUTPUT");
    let pid=args[1].parse()?;let tid:u32=args[2].parse()?;let count:u32=args[3].parse()?;let period:u64=args[4].parse()?;let address:usize=args[5].parse()?;
    ensure!(pid>0 && tid>0 && (1..=60).contains(&count) && (50..=1000).contains(&period) && u64::from(count)*period<=5000 && address%8==0,"Invalid capture limits");
    let mut out=BufWriter::new(OpenOptions::new().write(true).create_new(true).open(&args[6])?);
    let test=match std::env::var("IRONJUMP_WAITER_TEST_GATE") {
        Ok(prefix)=>{ensure!(count==1 && address!=0,"Synthetic gate requires one oracle sample");Some(TestGate{pre:Event::open(format!("{prefix}.pre"))?,go:Event::open(format!("{prefix}.go"))?})},Err(_)=>None,
    };
    let mut frequency=0;ensure!(unsafe{QueryPerformanceFrequency(&mut frequency)}!=0 && frequency>0,"No QPC");
    let init_begin=qpc();unsafe{SymSetOptions(0x80612);}
    let mut config=Config::default();config.full_filenames=true;config.native=false;config.blocking=LockingStrategy::NonBlocking;
    let initialized=(|| -> Result<_>{
        let spy=PythonSpy::new(pid,&config)?;ensure!(spy.version.major==3 && spy.version.minor==11,"Only qualified Python3.11 layout");
        let process=Process::new(pid)?;let symbols=process.symbolicator()?;let unwinder=process.unwinder()?;
        let requested=process.threads()?.into_iter().find(|t|t.id().ok()==Some(tid)).context("Requested PID/TID missing")?;
        Ok((spy,process,symbols,unwinder,requested))
    })();
    writeln!(out,"{}",json!({"kind":"init","schema":5,"pid":pid,"requested_tid":tid,"qpc_frequency":frequency,"qpc_begin":init_begin,"qpc_end":qpc(),"requested_count":count,"period_ms":period,"synthetic_probe_enabled":address!=0,"test_gate_enabled":test.is_some(),"mode":"requested thread context before global pause; symbolication after all samples","activity_flags_valid":false,"natural_owner_association_qualified":false,"field_attribution_ready":false,"error":initialized.as_ref().err().map(|e|format!("{e:#}"))}))?;out.flush()?;
    let (mut spy,process,symbols,unwinder,requested)=initialized?;
    let go=format!("{}.go",args[6]);let deadline=Instant::now()+Duration::from_secs(15);
    while !Path::new(&go).exists(){ensure!(Instant::now()<deadline,"Controller go timeout");thread::sleep(Duration::from_millis(1));}
    let mut samples=Vec::new();let mut capture_error=None;
    for ordinal in 0..count {
        let pacing=Instant::now();
        match snapshot(&mut spy,&process,&unwinder,&requested,ordinal,address,&test) {
            Ok(s)=>samples.push(s),Err(e)=>{capture_error=Some((ordinal,qpc(),e));break;}
        }
        if ordinal+1<count {thread::sleep(Duration::from_millis(period).saturating_sub(pacing.elapsed()));}
    }
    let collection_end=qpc();
    for s in samples {
        let resolve_begin=qpc();let pre=resolve(&s.pre_native,&process,&symbols);let native:Vec<_>=s.native.iter().map(|n|resolve(n,&process,&symbols)).collect();
        writeln!(out,"{}",json!({"kind":"sample","ordinal":s.ordinal,"pid":pid,"qpc_begin":s.begin,"qpc_end":s.end,"requested_suspend_call_qpc":s.request_call,"requested_locked_qpc":s.request_locked,"pre_context_begin_qpc":s.pre_begin,"pre_context_end_qpc":s.pre_end,"global_suspend_call_qpc":s.global_call,"suspended_qpc":s.global_locked,"global_resume_returned_qpc":s.global_resumed,"resume_returned_qpc":s.end,"collection_end_qpc":collection_end,"resolve_begin_qpc":resolve_begin,"resolve_end_qpc":qpc(),"pre_native":pre,"native":native,"traces":s.traces,"oracle_reads":s.oracle,"current_tstate_reads":s.current,"activity_flags_valid":false,"natural_owner_association_qualified":false}))?;
    }
    if let Some((ordinal,stamp,error))=capture_error {
        writeln!(out,"{}",json!({"kind":"error","ordinal":ordinal,"pid":pid,"qpc":stamp,"error":format!("{error:#}"),"prior_complete_samples_retained":ordinal}))?;out.flush()?;return Err(error);
    }
    writeln!(out,"{}",json!({"kind":"complete","pid":pid,"samples_written":count,"qpc":qpc()}))?;out.flush()?;Ok(())
}

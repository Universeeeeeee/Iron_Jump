//! Synthetic dynamic control with a GIL-independent native heartbeat.
use anyhow::{ensure, Context, Result};
use py_spy::{config::LockingStrategy, Config, PythonSpy};
use remoteprocess::{Process, Thread};
use serde_json::{json, Value};
use std::{fs::OpenOptions, io::{BufWriter, Write}, path::Path, thread, time::{Duration, Instant}};

#[link(name = "kernel32")]
extern "system" {
    fn QueryPerformanceCounter(value: *mut i64) -> i32;
    fn QueryPerformanceFrequency(value: *mut i64) -> i32;
    fn ReadProcessMemory(process: *mut std::ffi::c_void, address: usize, buffer: *mut u64, size: usize, read: *mut usize) -> i32;
}
#[link(name = "dbghelp")]
extern "system" { fn SymSetOptions(options: u32) -> u32; fn SymGetModuleBase64(process: *mut std::ffi::c_void, address: u64) -> u64; }
fn qpc() -> i64 { let mut n = 0; assert_ne!(unsafe { QueryPerformanceCounter(&mut n) }, 0); n }

struct Probe { begin: i64, end: i64, values: [u64; 4] }
fn probe(process: &Process, address: usize) -> Result<Probe> {
    let begin = qpc(); let mut values = [0u64; 4]; let mut read = 0;
    ensure!(unsafe { ReadProcessMemory(*process.handle, address, values.as_mut_ptr(), 32, &mut read) } != 0 && read == 32, "Native oracle read failed");
    Ok(Probe { begin, end: qpc(), values })
}
fn probe_json(p: &Probe) -> Value { json!({"qpc_begin":p.begin,"qpc_end":p.end,"values":p.values}) }

struct Native { tid: u32, ip: u64, sp: u64, bp: u64, addresses: Vec<u64>, stopped_by: &'static str }

fn snapshot(spy: &mut PythonSpy, process: &Process, unwinder: &remoteprocess::Unwinder,
            requested: u32, address: usize) -> Result<(Vec<py_spy::StackTrace>, Vec<Native>, i64, i64, [Probe; 2])> {
    // PythonSpy is configured nonblocking only because THIS scope owns the one
    // process lock. No independent Python/native snapshots are joined afterward.
    let lock = process.lock().context("NtSuspendProcess failed")?;
    let suspended = qpc();
    let first = probe(process, address)?;
    let traces = spy.get_stack_traces().context("Python read failed")?;
    ensure!(traces.iter().all(|t| t.pid == process.pid), "Python PID mismatch");
    let owners: Vec<_> = traces.iter().filter(|t| t.owns_gil).collect();
    ensure!(owners.len() <= 1, "Multiple GIL owners");
    let mut wanted = vec![requested];
    for t in owners { wanted.push(t.os_thread_id.context("Owner has no native TID")?.try_into()?); }
    wanted.sort_unstable(); wanted.dedup();
    // NtGetNextThread enumerates handles belonging to this process while paused.
    // Do not reopen an unrelated process's recycled numeric TID after resuming.
    let threads: Vec<Thread> = process.threads()?;
    let mut native = Vec::new();
    for tid in wanted {
        let t = threads.iter().find(|t| t.id().ok() == Some(tid)).context("Requested/owner OS thread missing")?;
        let mut cursor = unwinder.cursor(t).context("GetThreadContext failed")?;
        let (ip, sp, bp) = (cursor.ip(), cursor.sp(), cursor.bp());
        let mut addresses = vec![ip];
        let mut stopped_by = "StackWalk64 returned false; closure must be checked independently";
        for _ in 0..255 {
            match cursor.next() {
                Some(addr) => addresses.push(addr.context("Native unwind error")?),
                None => break,
            }
            if addresses.len() == 256 { stopped_by = "frame cap; incomplete"; }
        }
        native.push(Native { tid, ip, sp, bp, addresses, stopped_by });
    }
    // Drop checks NtResumeProcess. A failed resume panics and no successful row
    // is emitted. All formatting/symbolication/file I/O is after this drop.
    let last = probe(process, address)?;
    drop(lock);
    let resumed = qpc();
    Ok((traces, native, suspended, resumed, [first, last]))
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure!(args.len() == 7, "usage: candidate PID REQUESTED_TID COUNT PERIOD_MS ORACLE_ADDRESS NEW_OUTPUT");
    let pid: u32 = args[1].parse()?; let requested: u32 = args[2].parse()?;
    let count: u32 = args[3].parse()?; let period: u64 = args[4].parse()?;
    let address: usize = args[5].parse()?; ensure!(address > 0 && address % 8 == 0, "Invalid oracle address");
    ensure!(pid > 0 && requested > 0 && (1..=60).contains(&count), "invalid identities/count");
    ensure!((50..=1000).contains(&period) && u64::from(count)*period <= 5000, "rate/window exceeds synthetic limit");
    let file = OpenOptions::new().write(true).create_new(true).open(&args[6])?;
    let mut out = BufWriter::new(file); let mut frequency = 0;
    ensure!(unsafe { QueryPerformanceFrequency(&mut frequency) } != 0 && frequency > 0, "QPC unavailable");
    let begin = qpc(); unsafe { SymSetOptions(0x80612); } let mut config = Config::default(); config.full_filenames = true;
    config.blocking = LockingStrategy::NonBlocking; config.native = false;
    let initialized = (|| -> Result<_> {
        let spy = PythonSpy::new(pid, &config)?; let process = Process::new(pid)?;
        let symbols = process.symbolicator()?; let unwinder = process.unwinder()?;
        Ok((spy, process, symbols, unwinder))
    })();
    writeln!(out, "{}", json!({"kind":"init","schema":3,"pid":pid,"requested_tid":requested,
        "qpc_frequency":frequency,"qpc_begin":begin,"qpc_end":qpc(),"requested_count":count,
        "period_ms":period,"mode":"one external process lock; Python + unfiltered native; symbolication after resume",
        "activity_flags_valid":false,"field_attribution_ready":false,
        "error":initialized.as_ref().err().map(|e|format!("{e:#}"))}))?; out.flush()?;
    let (mut spy, process, symbols, unwinder) = initialized?;
    // Let the independent controller establish its native-marker phase AFTER
    // DbgHelp initialization, without guessing how long symbol loading takes.
    let go = format!("{}.go", &args[6]); let deadline = Instant::now()+Duration::from_secs(15);
    while !Path::new(&go).exists() { ensure!(Instant::now()<deadline,"Controller go timeout"); thread::sleep(Duration::from_millis(1)); }
    for ordinal in 0..count {
        let pacing = Instant::now(); let begin = qpc();
        let pre = probe(&process, address)?;
        let read = snapshot(&mut spy, &process, &unwinder, requested, address);
        let end = qpc();
        match read {
            Ok((traces, native, suspended, resumed, probes)) => {
                let post = probe(&process, address)?;
                let resolve_begin = qpc(); let mut resolved = Vec::new();
                for n in native {
                    let mut frames: Vec<Value> = Vec::new();
                    for address in n.addresses {
                        let base = unsafe { SymGetModuleBase64(*process.handle, address) };
                        let mut symbol = None;
                        let resolution = symbols.symbolicate(address, false, &mut |s| {
                            symbol = Some(json!({"function":s.function,"module":s.module,"filename":s.filename,"line":s.line}));
                        });
                        frames.push(json!({"address":address,"module_base":base,
                            "module_offset":if base>0 && address>=base {Some(address-base)}else{None},
                            "symbol":symbol,"symbol_error":resolution.err().map(|e|format!("{e}")),
                            "pdb_match_verified":false}));
                    }
                    resolved.push(json!({"tid":n.tid,"context_ip":n.ip,"context_sp":n.sp,"context_bp":n.bp,
                        "frames":frames,"stopped_by":n.stopped_by}));
                }
                writeln!(out,"{}",json!({"kind":"sample","ordinal":ordinal,"pid":pid,"qpc_begin":begin,"qpc_end":end,
                    "oracle_reads":[probe_json(&pre),probe_json(&probes[0]),probe_json(&probes[1]),probe_json(&post)],
                    "suspended_qpc":suspended,"resume_returned_qpc":resumed,"traces":traces,"native":resolved,
                    "resolve_begin_qpc":resolve_begin,"resolve_end_qpc":qpc(),"activity_flags_valid":false}))?;
            }
            Err(error) => {
                writeln!(out,"{}",json!({"kind":"error","ordinal":ordinal,"pid":pid,"qpc_begin":begin,
                    "qpc_end":end,"error":format!("{error:#}")}))?; out.flush()?; return Err(error);
            }
        }
        out.flush()?;
        if ordinal+1<count { thread::sleep(Duration::from_millis(period).saturating_sub(pacing.elapsed())); }
    }
    writeln!(out,"{}",json!({"kind":"complete","pid":pid,"samples_written":count,"qpc":qpc()}))?;
    out.flush()?; Ok(())
}

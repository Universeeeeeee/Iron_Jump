//! External Python snapshots. Keep each whole read bracket, including failures.
use anyhow::{ensure, Context, Result};
use py_spy::{Config, PythonSpy};
use serde_json::json;
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::thread;
use std::time::{Duration, Instant};

#[link(name = "kernel32")]
extern "system" {
    fn QueryPerformanceCounter(value: *mut i64) -> i32;
    fn QueryPerformanceFrequency(value: *mut i64) -> i32;
}

fn qpc() -> i64 {
    let mut value = 0;
    // QPC is available on supported Windows versions. No fallback clock is valid.
    assert_ne!(unsafe { QueryPerformanceCounter(&mut value) }, 0);
    value
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    ensure!(args.len() == 5, "usage: observer PID COUNT PERIOD_MS NEW_OUTPUT.jsonl");
    let pid: py_spy::Pid = args[1].parse()?;
    let count: u32 = args[2].parse()?;
    let period_ms: u64 = args[3].parse()?;
    ensure!(pid > 0 && (1..=200).contains(&count), "invalid PID/count");
    ensure!((20..=1000).contains(&period_ms) && u64::from(count) * period_ms <= 10000,
            "observation exceeds ten seconds or rate limit");
    let file = OpenOptions::new().write(true).create_new(true).open(&args[4])?;
    let mut out = BufWriter::new(file);
    let mut frequency = 0;
    ensure!(unsafe { QueryPerformanceFrequency(&mut frequency) } != 0 && frequency > 0,
            "QPC frequency unavailable");
    // Initialization is recorded separately, never charged to an individual read.
    // Use new(), not retry_new(): no unrecorded verification samples or retries.
    let init_start = qpc();
    let mut config = Config::default();
    config.full_filenames = true;
    let initialized = PythonSpy::new(pid, &config);
    let init_end = qpc();
    writeln!(out, "{}", json!({"kind":"init", "schema":1, "pid":pid,
        "qpc_frequency":frequency, "qpc_begin":init_start, "qpc_end":init_end,
        "requested_count":count, "period_ms":period_ms,
        "mode":"default blocking, Python frames, all threads",
        "error":initialized.as_ref().err().map(|e| format!("{e:#}"))}))?;
    out.flush()?;
    let mut spy = initialized.context("PythonSpy initialization failed; no retry")?;
    for ordinal in 0..count {
        let pacing = Instant::now();
        let begin = qpc();
        let sampled = spy.get_stack_traces();
        let end = qpc();
        // Upstream's process lock has dropped before get_stack_traces returns.
        // Serialization and file I/O happen after the complete read bracket.
        match sampled {
            Ok(traces) => writeln!(out, "{}", json!({"kind":"sample", "ordinal":ordinal,
                "pid":pid, "qpc_begin":begin, "qpc_end":end, "traces":traces}))?,
            Err(error) => {
                writeln!(out, "{}", json!({"kind":"error", "ordinal":ordinal,
                    "pid":pid, "qpc_begin":begin, "qpc_end":end,
                    "error":format!("{error:#}")}))?;
                out.flush()?;
                return Err(error.context("snapshot failed; remaining samples not attempted"));
            }
        }
        out.flush()?;
        if ordinal + 1 < count {
            thread::sleep(Duration::from_millis(period_ms).saturating_sub(pacing.elapsed()));
        }
    }
    writeln!(out, "{}", json!({"kind":"complete", "pid":pid,
        "samples_written":count, "qpc":qpc()}))?;
    out.flush()?;
    Ok(())
}

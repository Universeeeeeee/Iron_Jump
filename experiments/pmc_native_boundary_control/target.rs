// Local process only. Fixed native code and direct Win32 boundary calls; no crates.
use std::{ffi::c_void,fs::OpenOptions,io::Write};
#[repr(C)] #[derive(Default,Copy,Clone)] struct FileTime {low:u32,high:u32}
impl FileTime {fn value(self)->u64{(self.high as u64)<<32|self.low as u64}}
#[link(name="kernel32")] extern "system" {
    fn VirtualAlloc(p:*mut c_void,n:usize,t:u32,prot:u32)->*mut c_void;
    fn VirtualProtect(p:*mut c_void,n:usize,prot:u32,old:*mut u32)->i32;
    fn VirtualFree(p:*mut c_void,n:usize,t:u32)->i32;
    fn FlushInstructionCache(h:*mut c_void,p:*const c_void,n:usize)->i32;
    fn GetCurrentProcess()->*mut c_void;
    fn GetCurrentThread()->*mut c_void;
    fn GetCurrentThreadId()->u32;
    fn GetCurrentProcessId()->u32;
    fn GetThreadTimes(h:*mut c_void,a:*mut FileTime,b:*mut FileTime,c:*mut FileTime,d:*mut FileTime)->i32;
    fn QueryThreadCycleTime(h:*mut c_void,v:*mut u64)->i32;
    fn QueryPerformanceCounter(v:*mut i64)->i32;
    fn QueryPerformanceFrequency(v:*mut i64)->i32;
    fn Sleep(ms:u32);
}
const CODE:&[u8]=include_bytes!("code.bin");
struct Allocation(*mut c_void);
impl Allocation {
    unsafe fn new()->Self {
        let p=VirtualAlloc(std::ptr::null_mut(),CODE.len(),0x3000,4);assert!(!p.is_null());
        let memory=Self(p);std::ptr::copy_nonoverlapping(CODE.as_ptr(),p as *mut u8,CODE.len());
        let mut old=0;assert_ne!(VirtualProtect(p,CODE.len(),0x20,&mut old),0);
        assert_ne!(FlushInstructionCache(GetCurrentProcess(),p,CODE.len()),0);memory
    }
    unsafe fn call(&self,n:u64)->u64 {let f:extern "system" fn(u64)->u64=std::mem::transmute(self.0);f(n)}
    unsafe fn release(&mut self)->bool {let ok=VirtualFree(self.0,0,0x8000)!=0;if ok{self.0=std::ptr::null_mut();}ok}
}
impl Drop for Allocation {fn drop(&mut self){if !self.0.is_null(){unsafe{VirtualFree(self.0,0,0x8000);}}}}
#[derive(Copy,Clone)] struct Counter {tid:u32,creation:u64,kernel:u64,user:u64,cycles:u64}
unsafe fn counter()->Counter {
    let h=GetCurrentThread();let mut a=FileTime::default();let mut b=a;let mut c=a;let mut d=a;let mut cycles=0;
    assert_ne!(GetThreadTimes(h,&mut a,&mut b,&mut c,&mut d),0);assert_ne!(QueryThreadCycleTime(h,&mut cycles),0);
    Counter{tid:GetCurrentThreadId(),creation:a.value(),kernel:c.value(),user:d.value(),cycles}
}
impl Counter {fn json(self)->String{format!("{{\"tid\":{},\"creation_100ns\":{},\"kernel_100ns\":{},\"user_100ns\":{},\"cycles\":{}}}",self.tid,self.creation,self.kernel,self.user,self.cycles)}}
unsafe fn qpc()->i64 {let mut t=0;assert_ne!(QueryPerformanceCounter(&mut t),0);t}
struct Row {ordinal:usize,n:u64,value:u64,before:Counter,after:Counter,begin:i64,end:i64}
fn main(){unsafe {
    let mut memory=Allocation::new();for n in [1,2,17]{assert_eq!(memory.call(n),n*16);}
    let mut frequency=0;assert_ne!(QueryPerformanceFrequency(&mut frequency),0);
    let mut rows=Vec::with_capacity(8);
    for (ordinal,n) in [1,8_000_000,32_000_000,32_000_000,8_000_000,8_000_000,32_000_000,1].iter().enumerate(){
        Sleep(10);let before=counter();let begin=qpc();let value=memory.call(*n);let end=qpc();let after=counter();Sleep(10);
        assert_eq!(value,n*16);rows.push(Row{ordinal,n:*n,value,before,after,begin,end});
    }
    assert!(memory.release());
    let mut f=OpenOptions::new().write(true).create_new(true).open("native_target01.json").unwrap();
    writeln!(f,"{{\"pid\":{},\"tid\":{},\"frequency\":{},\"complete\":true,\"memory_released\":true,\"errors\":[],\"rows\":[",GetCurrentProcessId(),GetCurrentThreadId(),frequency).unwrap();
    for (i,r) in rows.iter().enumerate(){
        writeln!(f,"{}{{\"ordinal\":{},\"iterations\":{},\"value\":{},\"before\":{},\"after\":{},\"begin\":{{\"qpc_before\":{},\"qpc_after\":{}}},\"end\":{{\"qpc_before\":{},\"qpc_after\":{}}}}}",if i>0{","}else{""},r.ordinal,r.n,r.value,r.before.json(),r.after.json(),r.begin,r.begin,r.end,r.end).unwrap();
    }
    writeln!(f,"]}}").unwrap();
}}
#[cfg(test)] mod tests {use super::*;
    #[test] fn exact_code_shape(){assert_eq!(CODE.len(),72);assert_eq!(&CODE[..2],&[0x31,0xc0]);assert_eq!(&CODE[66..],&[0x48,0xff,0xc9,0x75,0xbb,0xc3]);for a in CODE[2..66].chunks(4){assert_eq!(a,&[0x48,0x83,0xc0,1]);}}
    #[test] fn actual_abi_output_and_release(){unsafe{let mut m=Allocation::new();for n in [1,2,17]{assert_eq!(m.call(n),n*16);}assert!(m.release());assert!(m.0.is_null());}}
    #[test] fn native_clocks_and_identity(){unsafe{let a=counter();let b=counter();assert_eq!(a.tid,b.tid);assert_eq!(a.creation,b.creation);assert!(b.user>=a.user && b.kernel>=a.kernel && b.cycles>=a.cycles);assert!(qpc()<=qpc());}}
}

// Direct thread boundary marker only. No counter activation, workload or global setter.
use std::ffi::c_void;
#[repr(C)] #[derive(Default,Copy,Clone)] struct FileTime {low:u32,high:u32}
impl FileTime {fn value(self)->u64{(self.high as u64)<<32|self.low as u64}}
#[repr(C)] #[derive(Default,Copy,Clone)] pub struct Marker {pub tid:u32,pub reserved:u32,pub creation:u64,pub kernel:u64,pub user:u64,pub cycles:u64,pub qpc:i64}
#[link(name="kernel32")] extern "system" {
    fn GetCurrentThread()->*mut c_void; fn GetCurrentThreadId()->u32;
    fn GetThreadTimes(h:*mut c_void,a:*mut FileTime,b:*mut FileTime,c:*mut FileTime,d:*mut FileTime)->i32;
    fn QueryThreadCycleTime(h:*mut c_void,v:*mut u64)->i32;
    fn QueryPerformanceCounter(v:*mut i64)->i32; fn Sleep(ms:u32);
}
unsafe fn mark(out:*mut Marker,begin:bool)->u32 {
    if out.is_null(){return 1;}if begin{Sleep(10);}
    let mut m=Marker::default();let mut a=FileTime::default();let mut b=a;let mut c=a;let mut d=a;
    if !begin && QueryPerformanceCounter(&mut m.qpc)==0{return 2;}
    if GetThreadTimes(GetCurrentThread(),&mut a,&mut b,&mut c,&mut d)==0{return 3;}
    if QueryThreadCycleTime(GetCurrentThread(),&mut m.cycles)==0{return 4;}
    m.tid=GetCurrentThreadId();m.creation=a.value();m.kernel=c.value();m.user=d.value();
    if begin && QueryPerformanceCounter(&mut m.qpc)==0{return 5;}
    *out=m;if !begin{Sleep(10);}0
}
#[no_mangle] pub unsafe extern "C" fn boundary_begin(out:*mut Marker)->u32{mark(out,true)}
#[no_mangle] pub unsafe extern "C" fn boundary_end(out:*mut Marker)->u32{mark(out,false)}
#[cfg(test)] mod tests {use super::*;
    #[test] fn abi_and_actual_identity(){unsafe{assert_eq!(std::mem::size_of::<Marker>(),48);let mut a=Marker::default();let mut b=a;assert_eq!(boundary_begin(&mut a),0);assert_eq!(boundary_end(&mut b),0);assert_eq!(a.tid,b.tid);assert_eq!(a.creation,b.creation);assert!(b.qpc>=a.qpc && b.cycles>=a.cycles && b.kernel>=a.kernel && b.user>=a.user);}}
    #[test] fn null_rejected(){unsafe{assert_ne!(boundary_begin(std::ptr::null_mut()),0);assert_ne!(boundary_end(std::ptr::null_mut()),0);}}
}

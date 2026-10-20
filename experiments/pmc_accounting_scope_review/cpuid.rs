// Read-only architectural identity/frequency leaves. No MSR, policy, affinity or power changes.
#[cfg(target_arch = "x86_64")]
fn main() {
    use std::arch::x86_64::__cpuid;
    unsafe {
        let zero = __cpuid(0);
        let vendor_bytes = [zero.ebx.to_le_bytes(), zero.edx.to_le_bytes(), zero.ecx.to_le_bytes()].concat();
        let vendor = String::from_utf8(vendor_bytes).unwrap();
        let one = __cpuid(1);
        let family = ((one.eax >> 8) & 0xf) + if ((one.eax >> 8) & 0xf) == 0xf { (one.eax >> 20) & 0xff } else { 0 };
        let base_model = (one.eax >> 4) & 0xf;
        let ext_model = (one.eax >> 16) & 0xf;
        let model = base_model + if family == 6 || family == 15 { ext_model << 4 } else { 0 };
        let stepping = one.eax & 0xf;
        let leaf15 = if zero.eax >= 0x15 { __cpuid(0x15) } else { std::mem::zeroed() };
        let leaf16 = if zero.eax >= 0x16 { __cpuid(0x16) } else { std::mem::zeroed() };
        println!("{{\"vendor\":\"{}\",\"max_basic_leaf\":{},\"family\":{},\"model\":{},\"stepping\":{},\"leaf15\":{{\"denominator\":{},\"numerator\":{},\"crystal_hz\":{},\"edx\":{}}},\"leaf16\":{{\"base_mhz\":{},\"max_mhz\":{},\"bus_mhz\":{}}}}}",
            vendor, zero.eax, family, model, stepping,
            leaf15.eax, leaf15.ebx, leaf15.ecx, leaf15.edx,
            leaf16.eax & 0xffff, leaf16.ebx & 0xffff, leaf16.ecx & 0xffff);
    }
}

#[cfg(not(target_arch = "x86_64"))]
compile_error!("This control is x86_64-only.");

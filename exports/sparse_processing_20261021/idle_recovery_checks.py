"""Idle path must resume identically after a real, monotonically numbered gap."""
import sys
import traceback
from experiment import *


def main():
    rows=[]
    for mode,cls in [('walk',WalkingProcessor),('run',OvergroundRunningProcessor)]:
        layout=DeviceLayout.linear(3)
        dev=PreparedDevice(layout,'synthetic',-1,0,3000)
        for kind in ('gap','invalid','masked'):
            a=cls(config_for(mode),dev)
            b=processor_class(cls,'idle')(config_for(mode),dev)
            for k in range(700):
                n=k+2 if kind=='gap' and k>=220 else k
                f=make_frame(layout,n,[(25,45)] if 50<=k<150 else [])
                if kind=='gap' and k==220:
                    f=replace(f,dropped_frames_before=2,quality_flags=('frame_gap',))
                if kind=='invalid' and k==220:
                    f=replace(f,valid_bits=bytes(layout.bit_count))
                masked=kind=='masked' and k==220
                a.process(f,masked_contact=masked)
                b.process(f,masked_contact=masked)
                assert_equal(state(a),state(b),(mode,kind,k))
            rows.append({'mode':mode,'case':kind,'frames':700,
                         'after_gap_counter_monotonic':True,
                         'idle_hits':b._exp_idle_hits,'exact':True})
    dump(HERE/'idle_recovery_checks.json',{'results':rows,'all_exact':True})
    print(rows,flush=True)


if __name__=='__main__':
    try:main()
    except BaseException:
        traceback.print_exc();sys.exit(1)

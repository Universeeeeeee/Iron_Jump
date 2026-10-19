import unittest
from control import run

class WorkIdentity(unittest.TestCase):
    def test_49_50_51ms_boundary(self):
        for gap,count in ((49,1),(50,2),(51,2)):
            r=run([dict(frame_id=1,logical_s=1.),dict(frame_id=2,logical_s=1+gap/1000)],[0,1]);self.assertEqual(len(r['inferences']),count)
    def test_fixed_timestamps_do_not_prevent_latest_only_overwrite(self):
        frames=[dict(frame_id=i,logical_s=1+i*.1) for i in range(3)]
        a=run(frames,[0,1,2]);b=run(frames,[2]);self.assertEqual(len(a['inferences']),3);self.assertEqual(len(b['inferences']),1);self.assertEqual(b['terminal'][0],['overwritten']);self.assertEqual(b['terminal'][1],['overwritten'])
    def test_duplicate_timestamp_rejected_by_original_scheduler(self):
        r=run([dict(frame_id=1,logical_s=1.),dict(frame_id=2,logical_s=1.)],[0,1]);self.assertEqual(r['terminal'][2],['nonincreasing_timestamp'])
    def test_same_schedule_same_work_independent_of_observer_clock(self):
        frames=[dict(frame_id=i,logical_s=1+i*.1) for i in range(3)];a=run(frames,[0,2]);b=run(frames,[0,2]);self.assertEqual(a['deterministic_work_sha256'],b['deterministic_work_sha256'])

if __name__=='__main__':unittest.main()

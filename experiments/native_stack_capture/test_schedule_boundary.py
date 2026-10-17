"""Only a proven pre-window left boundary may lack a preceding switch-in."""
import unittest
from analyze import schedule_residency


class ScheduleBoundaryTests(unittest.TestCase):
    def test_preexisting_out_before_window_retained_as_boundary(self):
        events=[(0,99,1,5,0),(10,1,99,2,0),(20,99,1,5,0)]
        running,errors,boundary=schedule_residency(events,1,5,25,1,True)
        self.assertEqual(running,10)
        self.assertEqual(errors,[])
        self.assertEqual(len(boundary),1)

    def test_initial_out_inside_window_still_rejected(self):
        running,errors,boundary=schedule_residency([(10,99,1,5,0)],1,5,25,1,True)
        self.assertEqual(errors,['out_without_in'])
        self.assertEqual(boundary,[])

    def test_new_thread_missing_switch_in_still_rejected(self):
        self.assertEqual(schedule_residency([(0,99,1,5,0)],1,5,25,1,False)[1],['out_without_in'])

    def test_internal_duplicate_out_still_rejected(self):
        events=[(0,99,1,5,0),(10,1,99,2,0),(20,99,1,5,0),(21,99,1,5,0)]
        self.assertEqual(schedule_residency(events,1,5,25,1,True)[1],['out_without_in'])

    def test_running_cpu_migration_still_rejected(self):
        self.assertEqual(schedule_residency([(10,1,99,2,0),(20,99,1,5,1)],1,5,25,1,True)[1],['cpu_changed_while_running'])


if __name__=='__main__':unittest.main()

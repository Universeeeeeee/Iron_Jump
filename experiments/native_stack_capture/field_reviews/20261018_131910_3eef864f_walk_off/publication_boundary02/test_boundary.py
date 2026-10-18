import unittest
from analyze import bracket


class PublicationBoundaryRegression(unittest.TestCase):
    def test_filtered_output_requires_its_outer_raw_delivery(self):
        # Output100 arrives while consuming raw110. Raw105 has completed first.
        rows=[[1000,99],[2000,105],[3000,120]]
        self.assertEqual(bracket(rows,110),(rows[1],rows[2]))
        self.assertNotEqual(bracket(rows,100),bracket(rows,110))

    def test_exact_completed_sample_is_in_upper_witness(self):
        rows=[[1000,99],[2000,105],[3000,120]]
        self.assertEqual(bracket(rows,105),(rows[0],rows[1]))

    def test_missing_future_completion_stays_unproven(self):
        with self.assertRaises(StopIteration):bracket([[1000,99],[2000,105]],110)


if __name__=='__main__':unittest.main()

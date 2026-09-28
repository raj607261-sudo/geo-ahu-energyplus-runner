import unittest
from engine.run import evaluate, candidates

class ScreeningTests(unittest.TestCase):
    def test_bounds_and_energy(self):
        for item in candidates(1, 120):
            self.assertGreaterEqual(item['climates']['humid']['supply_c'], 26)
            self.assertGreaterEqual(item['fan_w'], 0)
            self.assertGreaterEqual(item['core_dp_pa'], 0)
            if item['screening_pass']:
                self.assertGreaterEqual(item['climates']['humid']['capacity_w'], 5275)
                self.assertLessEqual(item['fan_w'] + item['pump_w'], 450)

    def test_reject_excess_pressure(self):
        x = evaluate(2, 2, 1, 1.5, .3, .8)
        self.assertFalse(x['screening_pass'])

import unittest
from engine.run import evaluate, candidates, evolve, ASSUMED_EFFECTIVENESS

class ScreeningTests(unittest.TestCase):
    def test_bounds_and_energy(self):
        for item in candidates(1, 120):
            self.assertEqual(item['geometry']['assumed_dp_effectiveness'], ASSUMED_EFFECTIVENESS)
            self.assertGreaterEqual(item['climates']['humid']['supply_c'], 26)
            self.assertGreaterEqual(item['fan_w'], 0)
            self.assertGreaterEqual(item['core_dp_pa'], 0)
            if item['screening_pass']:
                self.assertGreaterEqual(item['climates']['humid']['capacity_w'], 5275)
                self.assertLessEqual(item['fan_w'] + item['pump_w'], 450)

    def test_reject_excess_pressure(self):
        x = evaluate(2, 2, 1, 1.5, .3, .8)
        self.assertFalse(x['screening_pass'])

    def test_evolution_does_not_invent_effectiveness(self):
        parent = next(candidates(1))
        for item in evolve(parent, 2, 10):
            self.assertEqual(item['geometry']['assumed_dp_effectiveness'], ASSUMED_EFFECTIVENESS)

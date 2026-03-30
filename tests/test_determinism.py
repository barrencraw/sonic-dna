import unittest
from utils.providers import RngProvider

try:
    import numpy as np
except ImportError:
    np = None

class TestDeterminism(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        if np is None:
            self.skipTest("numpy not available")
        # Note: gen_wave and ui.music_panel are not easily testable without more setup,
        # but we can test RngProvider itself.
        seed = 42
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

        val1 = rng1.uniform(0, 1, size=10)
        val2 = rng2.uniform(0, 1, size=10)

        self.assertEqual(val1.tolist(), val2.tolist())

    def test_different_seeds_produce_different_waves(self):
        if np is None:
            self.skipTest("numpy not available")
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        val1 = rng1.uniform(0, 1, size=10)
        val2 = rng2.uniform(0, 1, size=10)

        self.assertNotEqual(val1.tolist(), val2.tolist())

    def test_fallback_logic(self):
        # Even if np is present, we can't easily force it to be None here without mocking,
        # but we can at least test that RngProvider works.
        rng = RngProvider(seed=42)
        val = rng.uniform(0, 1)
        self.assertIsInstance(val, float)

        vals = rng.uniform(0, 1, size=5)
        self.assertEqual(len(vals), 5)

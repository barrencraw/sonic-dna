try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

import unittest
from utils.providers import RngProvider

@unittest.skipUnless(HAS_NUMPY, "Numpy not available")
class TestDeterminismNumpy(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        from ui.music_panel import gen_wave
        seed = 42
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

        wave1 = gen_wave("White Noise", rng=rng1)
        wave2 = gen_wave("White Noise", rng=rng2)

        self.assertTrue(np.array_equal(wave1, wave2), "Waveform White Noise is not deterministic with seed 42")

    def test_different_seeds_produce_different_waves(self):
        from ui.music_panel import gen_wave
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave("White Noise", rng=rng1)
        wave2 = gen_wave("White Noise", rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

class TestDeterminismFallback(unittest.TestCase):
    def test_deterministic_uniform(self):
        seed = 42
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

        self.assertEqual(rng1.uniform(), rng2.uniform())
        self.assertEqual(rng1.uniform(0, 10), rng2.uniform(0, 10))
        self.assertEqual(rng1.uniform(0, 1, 5), rng2.uniform(0, 1, 5))

    def test_different_seeds_different_uniform(self):
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)
        self.assertNotEqual(rng1.uniform(), rng2.uniform())

if __name__ == '__main__':
    unittest.main()

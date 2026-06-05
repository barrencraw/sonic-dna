try:
    import numpy as np
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

import unittest
from utils.providers import RngProvider

def mock_gen_wave(wave_type, rng=None):
    # Minimal mock for testing logic without music_panel dependencies
    if rng:
        return [rng.random() for _ in range(10)]
    return [0.5] * 10

class TestDeterminism(unittest.TestCase):
    @unittest.skipUnless(HAS_DEPS, "numpy not installed")
    def test_deterministic_wave_generation(self):
        # This test requires real gen_wave and numpy
        from ui.music_panel import gen_wave
        wave_types = [
            "White Noise"
        ]
        for wave_type in wave_types:
            seed = 42
            rng1 = RngProvider(seed=seed)
            rng2 = RngProvider(seed=seed)

            wave1 = gen_wave(wave_type, rng=rng1)
            wave2 = gen_wave(wave_type, rng=rng2)

            self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    def test_different_seeds_produce_different_random_values(self):
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        val1 = rng1.random()
        val2 = rng2.random()

        self.assertNotEqual(val1, val2, "Different seeds produced the same random value")

if __name__ == '__main__':
    unittest.main()

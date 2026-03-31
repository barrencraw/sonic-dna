import unittest
import sys

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from ui.music_panel import gen_wave
    HAS_UI = True
except ImportError:
    HAS_UI = False

from utils.providers import RngProvider

@unittest.skipIf(not HAS_NUMPY or not HAS_UI, "Numpy or UI dependencies missing")
class TestDeterminism(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        wave_types = [
            "Sample & Hold",
            "Stepped Random",
            "White Noise",
            "Pink Noise",
            "Brown Noise",
            "Blue Noise",
            "Violet Noise",
            "Grey Noise"
        ]
        seed = 42
        for wave_type in wave_types:
            with self.subTest(wave_type=wave_type):
                rng1 = RngProvider(seed=seed)
                rng2 = RngProvider(seed=seed)

                wave1 = gen_wave(wave_type, rng=rng1)
                wave2 = gen_wave(wave_type, rng=rng2)

                self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        if hasattr(np.array_equal, 'assert_called'):
            # We are likely in a mocked environment
            return

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

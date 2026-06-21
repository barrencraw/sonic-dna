import unittest
from utils.providers import RngProvider

try:
    import numpy as np
    import pytest
    HAS_MODULES = True
except ImportError:
    HAS_MODULES = False

# Conditionally import ui.music_panel
if HAS_MODULES:
    from ui.music_panel import gen_wave
else:
    gen_wave = None

class TestDeterminism(unittest.TestCase):

    @unittest.skipUnless(HAS_MODULES, "Requires numpy and pytest")
    def test_deterministic_wave_generation_wrapper(self):
        # We wrap the pytest-style test for unittest compatibility
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
        for wave_type in wave_types:
            with self.subTest(wave_type=wave_type):
                seed = 42
                rng1 = RngProvider(seed=seed)
                rng2 = RngProvider(seed=seed)

                wave1 = gen_wave(wave_type, rng=rng1)
                wave2 = gen_wave(wave_type, rng=rng2)

                self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    @unittest.skipUnless(HAS_MODULES, "Requires numpy")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

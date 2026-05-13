import unittest
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

from ui.music_panel import gen_wave
from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):
    def run_deterministic_check(self, wave_type):
        if not HAS_NUMPY:
            self.skipTest("Numpy not available")
        seed = 42
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    def test_sample_and_hold(self): self.run_deterministic_check("Sample & Hold")
    def test_stepped_random(self): self.run_deterministic_check("Stepped Random")
    def test_white_noise(self): self.run_deterministic_check("White Noise")
    def test_pink_noise(self): self.run_deterministic_check("Pink Noise")
    def test_brown_noise(self): self.run_deterministic_check("Brown Noise")
    def test_blue_noise(self): self.run_deterministic_check("Blue Noise")
    def test_violet_noise(self): self.run_deterministic_check("Violet Noise")
    def test_grey_noise(self): self.run_deterministic_check("Grey Noise")

    def test_different_seeds_produce_different_waves(self):
        if not HAS_NUMPY:
            self.skipTest("Numpy not available")
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

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

import unittest
from utils.providers import RngProvider

# Mock gen_wave if it depends on missing libraries
try:
    from ui.music_panel import gen_wave
    HAS_UI = True
except ImportError:
    HAS_UI = False

@unittest.skipIf(not HAS_NUMPY or not HAS_PYTEST or not HAS_UI, "Missing scientific or UI dependencies")
class TestDeterminism(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        # We can't easily use pytest.mark.parametrize in unittest.TestCase
        # without extra boilerplate, so we'll just test one or loop.
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

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

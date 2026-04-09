import unittest
from utils.providers import RngProvider

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Mock gen_wave if it depends on science libs that might be missing
try:
    from ui.music_panel import gen_wave
    HAS_UI_DEPS = True
except ImportError:
    def gen_wave(wave_type, rng=None):
        # Fallback for testing RngProvider itself if UI deps missing
        return rng.uniform(0, 1, size=10)
    HAS_UI_DEPS = False

class TestDeterminism(unittest.TestCase):

    @unittest.skipIf(not HAS_NUMPY, "Numpy not installed")
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
            rng1 = RngProvider(seed=seed)
            rng2 = RngProvider(seed=seed)

            wave1 = gen_wave(wave_type, rng=rng1)
            wave2 = gen_wave(wave_type, rng=rng2)

            if HAS_NUMPY:
                self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")
            else:
                self.assertEqual(wave1, wave2)

    @unittest.skipIf(not HAS_NUMPY, "Numpy not installed")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        if HAS_NUMPY:
            self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")
        else:
            self.assertNotEqual(wave1, wave2)

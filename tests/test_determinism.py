import unittest
import random
from utils.providers import RngProvider

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# We might not be able to import gen_wave if PySide6 is missing,
# but providers.py and the core logic should still be testable.
try:
    from ui.music_panel import gen_wave
    HAS_UI_DEPS = True
except (ImportError, RuntimeError):
    HAS_UI_DEPS = False

class TestDeterminism(unittest.TestCase):

    @unittest.skipUnless(HAS_NUMPY and HAS_UI_DEPS, "Numpy or UI dependencies not installed")
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

            self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    @unittest.skipUnless(HAS_NUMPY and HAS_UI_DEPS, "Numpy or UI dependencies not installed")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

    def test_rng_provider_fallback_determinism(self):
        seed = 123
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

        # Test uniform
        v1 = rng1.uniform(0, 10, size=5)
        v2 = rng2.uniform(0, 10, size=5)
        self.assertEqual(v1, v2)

        # Test normal
        n1 = rng1.normal(0, 1, size=(2, 2))
        n2 = rng2.normal(0, 1, size=(2, 2))
        self.assertEqual(n1, n2)

    def test_rng_provider_different_seeds(self):
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        v1 = rng1.uniform(0, 1, size=10)
        v2 = rng2.uniform(0, 1, size=10)
        self.assertNotEqual(v1, v2)

if __name__ == '__main__':
    unittest.main()

try:
    import numpy as np
except ImportError:
    np = None
import unittest

try:
    from unittest.mock import MagicMock
except ImportError:
    MagicMock = None

def is_mock(obj):
    return MagicMock and isinstance(obj, MagicMock)

from ui.music_panel import gen_wave
from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):
    def is_numpy_array(self, obj):
        if np is None or is_mock(np):
            return False
        return hasattr(obj, 'shape') and hasattr(obj, 'dtype')

    @unittest.skipIf(np is None or is_mock(np), "numpy not installed or mocked")
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

    @unittest.skipIf(np is None or is_mock(np), "numpy not installed or mocked")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

    def test_rng_provider_fallback(self):
        """Test that RngProvider works without numpy."""
        rng = RngProvider(seed=42)
        # If np is mocked, rng.uniform returns a mock. We skip in that case.
        if is_mock(np):
            self.skipTest("Numpy is mocked, RngProvider uses mocked numpy")

        val = rng.uniform(0, 1)
        self.assertIsInstance(val, (float, list))

        vals = rng.uniform(0, 1, size=10)
        self.assertEqual(len(vals), 10)

if __name__ == '__main__':
    unittest.main()

from unittest.mock import MagicMock
import sys

try:
    import numpy as np
    # If it's a mock, it might not have 'array' or it might be a MagicMock
    HAS_NUMPY = hasattr(np, 'array') and not isinstance(np, MagicMock)
except ImportError:
    HAS_NUMPY = False

import unittest

# Mocking for environments without dependencies
if not HAS_NUMPY:
    if "numpy" not in sys.modules:
        mock_np = MagicMock()
        # Ensure np.array_equal returns a boolean-ish thing that evaluates to True for identity
        mock_np.array_equal.side_effect = lambda a, b: a is b
        sys.modules["numpy"] = mock_np
    else:
        # It's already mocked, try to add the side_effect if it's a mock
        mock_np = sys.modules["numpy"]
        if isinstance(mock_np, MagicMock):
            mock_np.array_equal.side_effect = lambda a, b: a is b

try:
    from ui.music_panel import gen_wave
    from utils.providers import RngProvider
    HAS_DEPS = HAS_NUMPY
except (ImportError, KeyError):
    HAS_DEPS = False

class TestDeterminism(unittest.TestCase):
    @unittest.skipUnless(HAS_DEPS, "Requires numpy and music_panel")
    def test_deterministic_wave_generation(self):
        seed = 42
        for wave_type in [
            "Sample & Hold",
            "Stepped Random",
            "White Noise",
            "Pink Noise",
            "Brown Noise",
            "Blue Noise",
            "Violet Noise",
            "Grey Noise"
        ]:
            rng1 = RngProvider(seed=seed)
            rng2 = RngProvider(seed=seed)

            wave1 = gen_wave(wave_type, rng=rng1)
            wave2 = gen_wave(wave_type, rng=rng2)

            self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    @unittest.skipUnless(HAS_DEPS, "Requires numpy and music_panel")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

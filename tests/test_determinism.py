import unittest
import sys
from unittest.mock import MagicMock

# Attempt to load actual dependencies, but mock if they are missing
HAS_DEPS = False
try:
    import numpy as np
    import scipy
    from ui.music_panel import gen_wave
    from utils.providers import RngProvider
    HAS_DEPS = True
except ImportError:
    # Setup mocks for environment that lacks scientific libs
    sys.modules['numpy'] = MagicMock()
    sys.modules['scipy'] = MagicMock()
    sys.modules['scipy.io'] = MagicMock()
    sys.modules['scipy.io.wavfile'] = MagicMock()
    sys.modules['sounddevice'] = MagicMock()
    sys.modules['PySide6'] = MagicMock()
    sys.modules['PySide6.QtWidgets'] = MagicMock()
    sys.modules['PySide6.QtCore'] = MagicMock()

    # We still need RngProvider for the class structure if we are mocking
    from utils.providers import RngProvider
    gen_wave = None

class TestDeterminism(unittest.TestCase):
    @unittest.skipUnless(HAS_DEPS, "Requires numpy and scipy")
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

    @unittest.skipUnless(HAS_DEPS, "Requires numpy and scipy")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

    def test_rng_provider_initialization(self):
        """Basic check that works even with mocks."""
        rng = RngProvider(seed=123)
        self.assertIsNotNone(rng._rng)

if __name__ == "__main__":
    unittest.main()

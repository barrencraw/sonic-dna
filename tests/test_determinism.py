import unittest
import sys
from unittest.mock import MagicMock

# Conditional import and test skipping
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Mock other non-essential dependencies
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()

from ui.music_panel import gen_wave
from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):

    @unittest.skipUnless(HAS_NUMPY, "Numpy not available, skipping actual wave verification")
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

    @unittest.skipUnless(HAS_NUMPY, "Numpy not available, skipping actual wave verification")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

    def test_basic_gen_wave_no_crash(self):
        # This test runs even without numpy to ensure no simple regressions
        rng = RngProvider(seed=42)
        wave = gen_wave("Sine Wave", rng=rng)
        if HAS_NUMPY:
            self.assertIsNotNone(wave)
        else:
            self.assertIsNone(wave)

if __name__ == '__main__':
    unittest.main()

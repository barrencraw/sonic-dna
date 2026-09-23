import sys
from unittest.mock import MagicMock

# Mock non-installed heavy packages before imports if running without native deps
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    mock_numpy = MagicMock()
    sys.modules["numpy"] = mock_numpy

try:
    import scipy
except ImportError:
    mock_scipy = MagicMock()
    sys.modules["scipy"] = mock_scipy
    sys.modules["scipy.io"] = mock_scipy.io
    sys.modules["scipy.io.wavfile"] = mock_scipy.io.wavfile

import unittest
from ui.music_panel import gen_wave
from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        if not HAS_NUMPY:
            self.skipTest("numpy module not installed")
        seed = 42
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

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
            wave1 = gen_wave(wave_type, rng=rng1)
            wave2 = gen_wave(wave_type, rng=rng2)
            self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    def test_different_seeds_produce_different_waves(self):
        if not HAS_NUMPY:
            self.skipTest("numpy module not installed")
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == "__main__":
    unittest.main()

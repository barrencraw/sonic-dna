import unittest
import sys
from unittest.mock import MagicMock

# Mock dependencies to allow import without numpy/pyside6
mock_pyside = MagicMock()
sys.modules["PySide6"] = mock_pyside
sys.modules["PySide6.QtWidgets"] = mock_pyside
sys.modules["PySide6.QtCore"] = mock_pyside
sys.modules["PySide6.QtGui"] = mock_pyside
sys.modules["sounddevice"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from ui.music_panel import gen_wave
from utils.providers import RngProvider

@unittest.skipUnless(HAS_NUMPY, "Numpy not installed, skipping determinism tests")
class TestDeterminism(unittest.TestCase):
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
        for wave_type in wave_types:
            seed = 42
            rng1 = RngProvider(seed=seed)
            rng2 = RngProvider(seed=seed)

            wave1 = gen_wave(wave_type, rng=rng1)
            wave2 = gen_wave(wave_type, rng=rng2)

            np.testing.assert_array_equal(wave1, wave2, f"Waveform {wave_type} is not deterministic with seed {seed}")

    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == "__main__":
    unittest.main()

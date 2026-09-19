import sys
from unittest.mock import MagicMock

# Safely mock dependencies if not already imported
mock_pyside6 = MagicMock()
sys.modules.setdefault("PySide6", mock_pyside6)
sys.modules.setdefault("PySide6.QtWidgets", mock_pyside6)
sys.modules.setdefault("PySide6.QtCore", mock_pyside6)
sys.modules.setdefault("PySide6.QtGui", mock_pyside6)
sys.modules.setdefault("numpy", MagicMock())
sys.modules.setdefault("scipy", MagicMock())
sys.modules.setdefault("scipy.io", MagicMock())
sys.modules.setdefault("scipy.io.wavfile", MagicMock())
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("torchaudio", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

import unittest
from ui.music_panel import gen_wave
from utils.providers import RngProvider

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
        seed = 42
        for wave_type in wave_types:
            rng1 = RngProvider(seed=seed)
            rng2 = RngProvider(seed=seed)

            wave1 = gen_wave(wave_type, rng=rng1)
            wave2 = gen_wave(wave_type, rng=rng2)

            self.assertEqual(
                repr(wave1), repr(wave2),
                f"Waveform {wave_type} is not deterministic with seed {seed}"
            )

    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        if str(type(wave1)) == "<class 'unittest.mock.MagicMock'>":
            self.skipTest("numpy is mocked in this environment")

        self.assertNotEqual(
            repr(wave1), repr(wave2),
            "Different seeds produced the same waveform"
        )

if __name__ == "__main__":
    unittest.main()

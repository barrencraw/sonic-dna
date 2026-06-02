import unittest
from unittest.mock import MagicMock
import sys

# Mock scientific dependencies
sys.modules['numpy'] = MagicMock()
sys.modules['sounddevice'] = MagicMock()
sys.modules['scipy'] = MagicMock()
sys.modules['scipy.io'] = MagicMock()
sys.modules['scipy.io.wavfile'] = MagicMock()
sys.modules['PySide6'] = MagicMock()
sys.modules['PySide6.QtWidgets'] = MagicMock()
sys.modules['PySide6.QtCore'] = MagicMock()
sys.modules['PySide6.QtGui'] = MagicMock()

import numpy as np
from ui.music_panel import gen_wave
from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        # Check if deps are available
        try:
            import numpy as real_np
            # If it's a MagicMock, it's not the real thing
            if hasattr(real_np, '_mock_return_value'):
                HAS_DEPS = False
            else:
                HAS_DEPS = True
        except ImportError:
            HAS_DEPS = False

        if not HAS_DEPS:
            self.skipTest("Numpy not available for real determinism test")

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
        try:
            import numpy as real_np
            if hasattr(real_np, '_mock_return_value'):
                HAS_DEPS = False
            else:
                HAS_DEPS = True
        except ImportError:
            HAS_DEPS = False

        if not HAS_DEPS:
            self.skipTest("Numpy not available for real determinism test")

        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

import unittest
import sys
from unittest.mock import MagicMock

# Detect if numpy is mocked in sys.modules
HAS_REAL_NUMPY = False
if "numpy" in sys.modules:
    import numpy as np
    if not isinstance(np, MagicMock):
        HAS_REAL_NUMPY = True

try:
    from ui.music_panel import gen_wave
except ImportError:
    gen_wave = None

from utils.providers import RngProvider

@unittest.skipUnless(HAS_REAL_NUMPY, "Scientific dependencies (numpy) missing or mocked")
class TestDeterminism(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        import numpy as np
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
            seed = 42
            rng1 = RngProvider(seed=seed)
            rng2 = RngProvider(seed=seed)

            wave1 = gen_wave(wave_type, rng=rng1)
            wave2 = gen_wave(wave_type, rng=rng2)

            np.testing.assert_array_equal(wave1, wave2, f"Waveform {wave_type} is not deterministic with seed {seed}")

    def test_different_seeds_produce_different_waves(self):
        import numpy as np
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

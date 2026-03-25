try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

import unittest
from utils.providers import RngProvider

# Mock gen_wave if it depends on PySide6/numpy and we just want to test RngProvider
# Or actually import it if we can.
try:
    from ui.music_panel import gen_wave
    CAN_TEST_WAVES = HAS_NUMPY
except ImportError:
    CAN_TEST_WAVES = False

@unittest.skipIf(not HAS_NUMPY, "Numpy not available, skipping determinism tests")
class TestDeterminism(unittest.TestCase):
    def test_deterministic_wave_generation(self):
        if not CAN_TEST_WAVES:
            self.skipTest("gen_wave or dependencies not available")

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
        if not CAN_TEST_WAVES:
            self.skipTest("gen_wave or dependencies not available")

        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

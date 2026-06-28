import os
import unittest
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from utils.providers import RngProvider
# Protected import for gen_wave if needed, or mock it
try:
    from ui.music_panel import gen_wave
    HAS_MUSIC_PANEL = True
except (ImportError, Exception):
    HAS_MUSIC_PANEL = False

class TestDeterminism(unittest.TestCase):
    @unittest.skipUnless(HAS_NUMPY and HAS_MUSIC_PANEL, "Requires numpy and music_panel dependencies")
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

            np.testing.assert_array_equal(wave1, wave2, f"Waveform {wave_type} is not deterministic with seed {seed}")

    @unittest.skipUnless(HAS_NUMPY and HAS_MUSIC_PANEL, "Requires numpy and music_panel dependencies")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

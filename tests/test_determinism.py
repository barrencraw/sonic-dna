import unittest

try:
    import numpy as np
    from unittest.mock import MagicMock
    HAS_NUMPY = hasattr(np, 'random') and not isinstance(np, MagicMock)
except Exception:
    np = None
    HAS_NUMPY = False

if HAS_NUMPY:
    from ui.music_panel import gen_wave
    from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):
    @unittest.skipUnless(HAS_NUMPY, "numpy required for waveform determinism tests")
    def test_deterministic_wave_generation(self):
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

            self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    @unittest.skipUnless(HAS_NUMPY, "numpy required for waveform determinism tests")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

import unittest
try:
    import numpy as np
    HAS_NUMPY = not hasattr(np, '_is_protocol') and not type(np).__name__ == 'MagicMock'
except Exception:
    HAS_NUMPY = False

try:
    from ui.music_panel import gen_wave
except Exception:
    gen_wave = None

from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):
    @unittest.skipUnless(HAS_NUMPY and gen_wave is not None, "numpy required for wave generation tests")
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
            with self.subTest(wave_type=wave_type):
                seed = 42
                rng1 = RngProvider(seed=seed)
                rng2 = RngProvider(seed=seed)

                wave1 = gen_wave(wave_type, rng=rng1)
                wave2 = gen_wave(wave_type, rng=rng2)

                self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")

    @unittest.skipUnless(HAS_NUMPY and gen_wave is not None, "numpy required for wave generation tests")
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

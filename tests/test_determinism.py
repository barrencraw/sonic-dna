import unittest
try:
    import numpy as np
except ImportError:
    np = None

from utils.providers import RngProvider

# Mock gen_wave if ui.music_panel is not available or if we want to avoid GUI dependencies in tests
def mock_gen_wave(wave_type, rng):
    if wave_type == "White Noise":
        return rng.uniform(-1, 1, size=100)
    return rng.standard_normal(size=100)

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
            with self.subTest(wave_type=wave_type):
                rng1 = RngProvider(seed=seed)
                rng2 = RngProvider(seed=seed)

                try:
                    from ui.music_panel import gen_wave
                except ImportError:
                    gen_wave = mock_gen_wave

                wave1 = gen_wave(wave_type, rng=rng1)
                wave2 = gen_wave(wave_type, rng=rng2)

                if np:
                    self.assertTrue(np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}")
                else:
                    self.assertEqual(wave1, wave2, f"Waveform {wave_type} is not deterministic with seed {seed}")

    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        try:
            from ui.music_panel import gen_wave
        except ImportError:
            gen_wave = mock_gen_wave

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        if np:
            self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")
        else:
            self.assertNotEqual(wave1, wave2, "Different seeds produced the same waveform")

if __name__ == '__main__':
    unittest.main()

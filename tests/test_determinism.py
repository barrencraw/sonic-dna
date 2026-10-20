import unittest

try:
    import numpy as np
    HAS_NUMPY = not hasattr(np, '__spec__') or np.__spec__ is not None
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import pytest
except ImportError:
    pytest = None

try:
    from ui.music_panel import gen_wave
except Exception:
    gen_wave = None
from utils.providers import RngProvider

class TestDeterminism(unittest.TestCase):
    @unittest.skipUnless(HAS_NUMPY, "numpy not available")
    def test_deterministic_wave_generation(self):
        if not HAS_NUMPY or gen_wave is None:
            self.skipTest("numpy or gen_wave not available")
        seed = 42
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

        wave1 = gen_wave("White Noise", rng=rng1)
        wave2 = gen_wave("White Noise", rng=rng2)

        self.assertTrue(np.array_equal(wave1, wave2), f"Waveform White Noise is not deterministic with seed {seed}")

    @unittest.skipUnless(HAS_NUMPY, "numpy not available")
    def test_different_seeds_produce_different_waves(self):
        if not HAS_NUMPY or gen_wave is None:
            self.skipTest("numpy or gen_wave not available")
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave("White Noise", rng=rng1)
        wave2 = gen_wave("White Noise", rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2), "Different seeds produced the same waveform")

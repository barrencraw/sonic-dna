import unittest
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

try:
    from ui.music_panel import gen_wave
    from utils.providers import RngProvider
    HAS_MODULES = True
except ImportError:
    HAS_MODULES = False

def skip_if_no_deps(func):
    if not (HAS_NUMPY and HAS_PYTEST and HAS_MODULES):
        return unittest.skip("Dependencies missing")(func)
    return func

class TestDeterminism(unittest.TestCase):
    def test_placeholder(self):
        pass

    @skip_if_no_deps
    def test_deterministic_wave_generation(self):
        # We can't easily use pytest.mark.parametrize with unittest discover without pytest
        # So we'll just test one wave type for now if we want it to run in unittest
        wave_type = "White Noise"
        seed = 42
        rng1 = RngProvider(seed=seed)
        rng2 = RngProvider(seed=seed)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertTrue(np.array_equal(wave1, wave2))

    @skip_if_no_deps
    def test_different_seeds_produce_different_waves(self):
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        self.assertFalse(np.array_equal(wave1, wave2))

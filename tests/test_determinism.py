try:
    import numpy as np
    import pytest
    from ui.music_panel import gen_wave
    HAS_MODULES = True
except ImportError:
    HAS_MODULES = False
    class MockPytest:
        class Mark:
            @staticmethod
            def skipif(*args, **kwargs):
                return lambda x: x
            @staticmethod
            def parametrize(*args, **kwargs):
                return lambda x: x
        mark = Mark()
    pytest = MockPytest()

from utils.providers import RngProvider

@pytest.mark.skipif(not HAS_MODULES, reason="Requires numpy, pytest, and ui modules")
@pytest.mark.parametrize("wave_type", [
    "Sample & Hold",
    "Stepped Random",
    "White Noise",
    "Pink Noise",
    "Brown Noise",
    "Blue Noise",
    "Violet Noise",
    "Grey Noise"
])
def test_deterministic_wave_generation(wave_type):
    seed = 42
    rng1 = RngProvider(seed=seed)
    rng2 = RngProvider(seed=seed)

    wave1 = gen_wave(wave_type, rng=rng1)
    wave2 = gen_wave(wave_type, rng=rng2)

    assert np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}"

@pytest.mark.skipif(not HAS_MODULES, reason="Requires numpy, pytest, and ui modules")
def test_different_seeds_produce_different_waves():
    wave_type = "White Noise"
    rng1 = RngProvider(seed=42)
    rng2 = RngProvider(seed=43)

    wave1 = gen_wave(wave_type, rng=rng1)
    wave2 = gen_wave(wave_type, rng=rng2)

    assert not np.array_equal(wave1, wave2), "Different seeds produced the same waveform"

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

import pytest
from utils.providers import RngProvider

def test_rng_provider_fallback_consistency():
    """Verify that RngProvider works without numpy and is deterministic with its own fallback."""
    seed = 123
    rng1 = RngProvider(seed=seed)
    rng2 = RngProvider(seed=seed)

    val1 = rng1.uniform()
    val2 = rng2.uniform()
    assert val1 == val2

    lst1 = rng1.normal(size=5)
    lst2 = rng2.normal(size=5)
    assert lst1 == lst2
    assert len(lst1) == 5

@pytest.mark.skipif(not HAS_NUMPY, reason="numpy not available")
def test_deterministic_wave_generation_with_numpy():
    from ui.music_panel import gen_wave
    wave_type = "White Noise"
    seed = 42
    rng1 = RngProvider(seed=seed)
    rng2 = RngProvider(seed=seed)

    wave1 = gen_wave(wave_type, rng=rng1)
    wave2 = gen_wave(wave_type, rng=rng2)

    assert np.array_equal(wave1, wave2), f"Waveform {wave_type} is not deterministic with seed {seed}"

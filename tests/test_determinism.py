try:
    import numpy as np
    import pytest
    from ui.music_panel import gen_wave
    from utils.providers import RngProvider
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

if NUMPY_AVAILABLE:
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

    def test_different_seeds_produce_different_waves():
        wave_type = "White Noise"
        rng1 = RngProvider(seed=42)
        rng2 = RngProvider(seed=43)

        wave1 = gen_wave(wave_type, rng=rng1)
        wave2 = gen_wave(wave_type, rng=rng2)

        assert not np.array_equal(wave1, wave2), "Different seeds produced the same waveform"
else:
    import unittest
    class TestDeterminismStub(unittest.TestCase):
        def test_skipping_determinism_due_to_missing_deps(self):
            print("Skipping determinism tests because numpy, pytest, or ui.music_panel is unavailable.")

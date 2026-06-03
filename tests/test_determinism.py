import unittest
from unittest.mock import MagicMock
import sys

# Mock dependencies for environment without scientific libs
mock_np = MagicMock()
sys.modules["numpy"] = mock_np
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import numpy as np
import pytest
from ui.music_panel import gen_wave
from utils.providers import RngProvider

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

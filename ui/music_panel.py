try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from scipy.io.wavfile import write as write_wav
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import sounddevice as sd
except (OSError, ImportError):
    sd = None

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QComboBox
)
from PySide6.QtGui import QPainter, QPen, QColor

import random
import math

# Constants
SAMPLE_RATE = 44100
DURATION = 2.0
FREQ = 440

BASE_SOUNDS = [
    "Sine Wave",
    "Square Wave",
    "Triangle Wave",
    "Sawtooth Wave",
    "Pulse Wave",
    "Supersaw",
    "Organ (Additive)",
    "Ring Modulated",
    "Impulse",
    "Click",
    "Burst",
    "DC Offset",
    "Silence",
    "Sample & Hold",
    "Stepped Random",
    "Linear Chirp",
    "White Noise",
    "Pink Noise",
    "Brown Noise",
    "Blue Noise",
    "Violet Noise",
    "Grey Noise"
]

def gen_wave(wave_type, volume=0.8, rng=None):
    num_samples = int(SAMPLE_RATE * DURATION)

    if HAS_NUMPY:
        t = np.linspace(0, DURATION, num_samples, endpoint=False)
    else:
        t = [i / SAMPLE_RATE for i in range(num_samples)]

    if rng is None:
        from utils.providers import RngProvider
        rng = RngProvider()

    if wave_type == "Sine Wave":
        if HAS_NUMPY:
            return volume * np.sin(2 * np.pi * FREQ * t)
        else:
            return [volume * math.sin(2 * math.pi * FREQ * ti) for ti in t]

    elif wave_type == "Square Wave":
        if HAS_NUMPY:
            return volume * np.sign(np.sin(2 * np.pi * FREQ * t))
        else:
            return [volume * (1 if math.sin(2 * math.pi * FREQ * ti) >= 0 else -1) for ti in t]

    elif wave_type == "Triangle Wave":
        if HAS_NUMPY:
            return volume * (2 * np.abs(2 * ((t * FREQ) % 1) - 1) - 1)
        else:
            return [volume * (2 * abs(2 * ((ti * FREQ) % 1) - 1) - 1) for ti in t]

    elif wave_type == "Sawtooth Wave":
        if HAS_NUMPY:
            return volume * (2 * ((t * FREQ) % 1) - 1)
        else:
            return [volume * (2 * ((ti * FREQ) % 1) - 1) for ti in t]

    elif wave_type == "Pulse Wave":
        pulse_width = 0.2
        if HAS_NUMPY:
            return volume * np.where((t * FREQ) % 1 < pulse_width, 1, -1)
        else:
            return [volume * (1 if (ti * FREQ) % 1 < pulse_width else -1) for ti in t]

    elif wave_type == "Supersaw":
        detunes = [FREQ*0.98, FREQ*0.99, FREQ, FREQ*1.01, FREQ*1.02]
        if HAS_NUMPY:
            sum_saws = sum(np.sin(2 * np.pi * d * t) for d in detunes)
            return volume * (sum_saws / len(detunes))
        else:
            res = []
            for ti in t:
                s = sum(math.sin(2 * math.pi * d * ti) for d in detunes)
                res.append(volume * (s / len(detunes)))
            return res

    elif wave_type == "Organ (Additive)":
        harmonics = [1, 2, 3, 4, 5]
        amps = [1.0, 0.5, 0.25, 0.13, 0.06]
        if HAS_NUMPY:
            organ = sum(a * np.sin(2 * np.pi * FREQ * h * t) for a, h in zip(amps, harmonics))
            return volume * (organ / sum(amps))
        else:
            res = []
            total_amp = sum(amps)
            for ti in t:
                s = sum(a * math.sin(2 * math.pi * FREQ * h * ti) for a, h in zip(amps, harmonics))
                res.append(volume * (s / total_amp))
            return res

    elif wave_type == "Ring Modulated":
        mod_freq = 55
        if HAS_NUMPY:
            return volume * np.sin(2 * np.pi * FREQ * t) * np.sin(2 * np.pi * mod_freq * t)
        else:
            return [volume * math.sin(2 * math.pi * FREQ * ti) * math.sin(2 * math.pi * mod_freq * ti) for ti in t]

    elif wave_type == "Impulse":
        if HAS_NUMPY:
            data = np.zeros_like(t)
            data[0] = 1
            return volume * data
        else:
            data = [0.0] * num_samples
            data[0] = 1.0
            return [volume * d for d in data]

    elif wave_type == "Click":
        click_samples = int(0.002 * SAMPLE_RATE)
        if HAS_NUMPY:
            data = np.zeros_like(t)
            data[:click_samples] = 1
            return volume * data
        else:
            data = [1.0 if i < click_samples else 0.0 for i in range(num_samples)]
            return [volume * d for d in data]

    elif wave_type == "Burst":
        burst_len = int(0.1 * SAMPLE_RATE)
        if HAS_NUMPY:
            data = np.zeros_like(t)
            data[:burst_len] = np.sin(2 * np.pi * FREQ * t[:burst_len])
            return volume * data
        else:
            data = [math.sin(2 * math.pi * FREQ * ti) if i < burst_len else 0.0 for i, ti in enumerate(t)]
            return [volume * d for d in data]

    elif wave_type == "DC Offset":
        if HAS_NUMPY:
            return volume * np.ones_like(t)
        else:
            return [volume] * num_samples

    elif wave_type == "Silence":
        if HAS_NUMPY:
            return np.zeros_like(t)
        else:
            return [0.0] * num_samples

    elif wave_type == "Sample & Hold":
        steps = 32
        step_len = num_samples // steps
        vals = rng.uniform(-1, 1, steps)
        if HAS_NUMPY:
            data = np.repeat(vals, step_len)
            data = np.pad(data, (0, num_samples - len(data)))
            return volume * data
        else:
            data = []
            for v in vals:
                data.extend([v] * step_len)
            while len(data) < num_samples:
                data.append(0.0)
            return [volume * d for d in data]

    elif wave_type == "Stepped Random":
        steps = 16
        vals = rng.uniform(-1, 1, steps+1)
        if HAS_NUMPY:
            idx = np.floor(np.linspace(0, steps, num_samples)).astype(int)
            return volume * vals[idx]
        else:
            data = []
            for i in range(num_samples):
                idx = int((i / num_samples) * steps)
                data.append(volume * vals[idx])
            return data

    elif wave_type == "Linear Chirp":
        f0, f1 = 220, 1760
        if HAS_NUMPY:
            chirp = np.sin(2 * np.pi * (f0 + (f1 - f0) * t / DURATION / 2) * t)
            return volume * chirp
        else:
            return [volume * math.sin(2 * math.pi * (f0 + (f1 - f0) * ti / DURATION / 2) * ti) for ti in t]

    elif wave_type == "White Noise":
        return [volume * v for v in rng.uniform(-1, 1, num_samples)]

    elif wave_type == "Pink Noise":
        # Simplified pink noise implementation if numpy is missing
        if HAS_NUMPY:
            nrows, ncols = 16, num_samples
            array = rng.standard_normal((nrows, ncols))
            array = np.cumsum(array, axis=0)
            pink = array[-1] / np.max(np.abs(array[-1]))
            return volume * pink
        else:
            # Fallback to white noise for simplicity in non-numpy env
            return [volume * v for v in rng.uniform(-1, 1, num_samples)]

    elif wave_type == "Brown Noise":
        wn = rng.uniform(-1, 1, num_samples)
        if HAS_NUMPY:
            brown = np.cumsum(wn)
            brown = brown / np.max(np.abs(brown))
            return volume * brown
        else:
            brown = []
            curr = 0
            for v in wn:
                curr += v
                brown.append(curr)
            m = max(abs(b) for b in brown) if brown else 1
            return [volume * b / m for b in brown]

    # Blue, Violet, Grey Noise heavily depend on FFT or complex array ops.
    # We provide basic white noise fallback if no numpy.
    elif wave_type in ["Blue Noise", "Violet Noise", "Grey Noise"]:
        if HAS_NUMPY:
            white = rng.normal(0, 1, num_samples)
            fft = np.fft.rfft(white)
            freqs = np.fft.rfftfreq(num_samples, 1 / SAMPLE_RATE)
            if wave_type == "Blue Noise":
                fft *= np.sqrt(freqs)
            elif wave_type == "Violet Noise":
                fft *= freqs
            elif wave_type == "Grey Noise":
                # Grey noise simplified as EQ'd white
                eq_curve = np.linspace(0.6, 1.2, num_samples)
                return volume * (white * eq_curve / np.max(np.abs(white * eq_curve)))

            res = np.fft.irfft(fft)
            res = res / np.max(np.abs(res))
            return volume * res
        else:
            return [volume * v for v in rng.uniform(-1, 1, num_samples)]

    else:
        return [0.0] * num_samples

class WaveformWidget(QWidget):
    def __init__(self):
        super().__init__()
        if HAS_NUMPY:
            self.data = np.zeros(512)
        else:
            self.data = [0.0] * 512
        self.setMinimumHeight(140)

    def set_wave(self, data):
        if HAS_NUMPY:
            self.data = data[:512] if len(data) > 512 else np.pad(data, (0, max(0, 512 - len(data))))
        else:
            self.data = data[:512]
            while len(self.data) < 512:
                self.data.append(0.0)
        self.update()

    def paintEvent(self, event):
        qp = QPainter(self)
        qp.fillRect(event.rect(), Qt.black)
        w, h = self.width(), self.height()
        pen = QPen(QColor(0, 220, 255), 2)
        qp.setPen(pen)
        mid = h // 2
        N = len(self.data)
        for i in range(1, N):
            x0 = int((i-1) * w / N)
            y0 = int(mid - self.data[i-1] * (h//2 - 10))
            x1 = int(i * w / N)
            y1 = int(mid - self.data[i] * (h//2 - 10))
            qp.drawLine(x0, y0, x1, y1)

class MusicPanel(QWidget):
    def __init__(self, rng=None):
        super().__init__()
        self.rng = rng
        layout = QVBoxLayout(self)

        # Dropdown for sound selection
        top = QHBoxLayout()
        self.sound_selector = QComboBox()
        self.sound_selector.addItems(BASE_SOUNDS)
        top.addWidget(QLabel("Base Sound:"))
        top.addWidget(self.sound_selector)
        layout.addLayout(top)

        # Waveform display
        self.waveform = WaveformWidget()
        layout.addWidget(self.waveform)

        # Play/Pause button
        self.play_btn = QPushButton("Play")
        layout.addWidget(self.play_btn)

        #Download Audio
        self.download_btn = QPushButton("Download")
        layout.addWidget(self.download_btn)
        self.download_btn.clicked.connect(self.download_wave)

        # State
        self.current_wave = None
        self.is_playing = False

        # Signals
        self.sound_selector.currentTextChanged.connect(self.update_waveform)
        self.play_btn.clicked.connect(self.toggle_play)

        self.update_waveform()  # Initialize display

    def update_waveform(self):
        wave_type = self.sound_selector.currentText()
        data = gen_wave(wave_type, rng=self.rng)
        self.current_wave = data
        self.waveform.set_wave(data)
        if self.is_playing:
            self.toggle_play()  # Stop if user changes wave while playing

    def toggle_play(self):
        if not self.is_playing:
            self.is_playing = True
            self.play_btn.setText("Pause")
            if sd:
                sd.play(self.current_wave, samplerate=SAMPLE_RATE)
            else:
                print("Sounddevice not available, cannot play.")
        else:
            self.is_playing = False
            self.play_btn.setText("Play")
            if sd:
                sd.stop()

    def download_wave(self):
        if self.current_wave is not None:
            file_path, _ = QFileDialog.getSaveFileName(self, "Save WAV File", "sound.wav", "WAV Files (*.wav)")
            if file_path:
                if HAS_NUMPY:
                    # Normalize to 16-bit PCM for WAV export
                    audio = (self.current_wave * 32767).astype(np.int16)
                    if HAS_SCIPY:
                        write_wav(file_path, SAMPLE_RATE, audio)
                else:
                    # Manual basic WAV export is complex, skipped if no numpy/scipy
                    print("WAV export requires numpy and scipy.")

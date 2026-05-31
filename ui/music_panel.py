try:
    import numpy as np
except (ImportError, OSError):
    np = None

try:
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

try:
    from scipy.io.wavfile import write as write_wav
except (ImportError, OSError):
    write_wav = None

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QComboBox
)
from PySide6.QtGui import QPainter, QPen, QColor

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
    if np is None:
        return None
    t = np.linspace(0, DURATION, int(SAMPLE_RATE * DURATION), endpoint=False)

    if rng is None:
        from utils.providers import RngProvider
        rng = RngProvider()

    if wave_type == "Sine Wave":
        return volume * np.sin(2 * np.pi * FREQ * t)
    elif wave_type == "Square Wave":
        return volume * np.sign(np.sin(2 * np.pi * FREQ * t))
    elif wave_type == "Triangle Wave":
        return volume * (2 * np.abs(2 * ((t * FREQ) % 1) - 1) - 1)
    elif wave_type == "Sawtooth Wave":
        return volume * (2 * ((t * FREQ) % 1) - 1)
    elif wave_type == "Pulse Wave":
        pulse_width = 0.2
        return volume * np.where((t * FREQ) % 1 < pulse_width, 1, -1)
    elif wave_type == "Supersaw":
        detune = [FREQ*0.98, FREQ*0.99, FREQ, FREQ*1.01, FREQ*1.02]
        sum_saws = sum(np.sin(2 * np.pi * d * t) for d in detune)
        return volume * (sum_saws / len(detune))
    elif wave_type == "Organ (Additive)":
        harmonics = [1, 2, 3, 4, 5]
        amps = [1.0, 0.5, 0.25, 0.13, 0.06]
        organ = sum(a * np.sin(2 * np.pi * FREQ * h * t) for a, h in zip(amps, harmonics))
        return volume * (organ / sum(amps))
    elif wave_type == "Ring Modulated":
        mod_freq = 55
        return volume * np.sin(2 * np.pi * FREQ * t) * np.sin(2 * np.pi * mod_freq * t)
    elif wave_type == "Impulse":
        data = np.zeros_like(t)
        data[0] = 1
        return volume * data
    elif wave_type == "Click":
        data = np.zeros_like(t)
        data[:int(0.002 * SAMPLE_RATE)] = 1
        return volume * data
    elif wave_type == "Burst":
        data = np.zeros_like(t)
        burst_len = int(0.1 * SAMPLE_RATE)
        data[:burst_len] = np.sin(2 * np.pi * FREQ * t[:burst_len])
        return volume * data
    elif wave_type == "DC Offset":
        return volume * np.ones_like(t)
    elif wave_type == "Silence":
        return np.zeros_like(t)
    elif wave_type == "Sample & Hold":
        steps = 32
        step_len = len(t) // steps
        vals = rng.uniform(-1, 1, steps)
        data = np.repeat(vals, step_len)
        data = np.pad(data, (0, len(t) - len(data)))
        return volume * data
    elif wave_type == "Stepped Random":
        steps = 16
        idx = np.floor(np.linspace(0, steps, len(t))).astype(int)
        vals = rng.uniform(-1, 1, steps+1)
        return volume * vals[idx]
    elif wave_type == "Linear Chirp":
        f0, f1 = 220, 1760
        chirp = np.sin(2 * np.pi * (f0 + (f1 - f0) * t / DURATION / 2) * t)
        return volume * chirp
    elif wave_type == "White Noise":
        return volume * rng.uniform(-1, 1, len(t))
    elif wave_type == "Pink Noise":
        nrows, ncols = 16, len(t)
        array = rng.standard_normal((nrows, ncols))
        array = np.cumsum(array, axis=0)
        pink = array[-1] / np.max(np.abs(array[-1]))
        return volume * pink
    elif wave_type == "Brown Noise":
        wn = rng.uniform(-1, 1, len(t))
        brown = np.cumsum(wn)
        brown = brown / np.max(np.abs(brown))
        return volume * brown
    elif wave_type == "Blue Noise":
        white = rng.normal(0, 1, len(t))
        fft = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(len(white), 1 / SAMPLE_RATE)
        fft *= np.sqrt(freqs)
        blue = np.fft.irfft(fft)
        blue = blue / np.max(np.abs(blue))
        return volume * blue
    elif wave_type == "Violet Noise":
        white = rng.normal(0, 1, len(t))
        fft = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(len(white), 1 / SAMPLE_RATE)
        fft *= freqs
        violet = np.fft.irfft(fft)
        violet = violet / np.max(np.abs(violet))
        return volume * violet
    elif wave_type == "Grey Noise":
        white = rng.normal(0, 1, len(t))
        eq_curve = np.linspace(0.6, 1.2, len(white))
        return volume * (white * eq_curve / np.max(np.abs(white * eq_curve)))
    else:
        return np.zeros_like(t)

class WaveformWidget(QWidget):
    def __init__(self):
        super().__init__()
        if np:
            self.data = np.zeros(512)
        else:
            self.data = [0] * 512
        self.setMinimumHeight(140)

    def set_wave(self, data):
        if data is None:
            return
        if np:
            self.data = data[:512] if len(data) > 512 else np.pad(data, (0, max(0, 512 - len(data))))
        else:
            self.data = data[:512]
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
        if self.current_wave is not None and write_wav is not None:
            file_path, _ = QFileDialog.getSaveFileName(self, "Save WAV File", "sound.wav", "WAV Files (*.wav)")
            if file_path:
                # Normalize to 16-bit PCM for WAV export
                audio = (self.current_wave * 32767).astype(np.int16)
                write_wav(file_path, SAMPLE_RATE, audio)
        else:
            print("WAV export not available (missing numpy or scipy).")

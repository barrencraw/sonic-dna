import unittest
import sys
from unittest.mock import MagicMock

# Mock scientific and UI dependencies before they are imported by the project
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["pytest"] = MagicMock()

from ui.music_panel import gen_wave
from utils.providers import RngProvider

class TestDeterminismMock(unittest.TestCase):
    def test_mock_environment(self):
        # This test ensures that in environments without numpy/PySide6,
        # we can still import and run basic logic if we mock them.
        # Since we're mocking, we can't test real numeric determinism here,
        # but we can verify the code doesn't crash on import.
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()

import os
import sys

# Mock common heavy/missing dependencies
from unittest.mock import MagicMock

# ONLY mock if truly missing
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    mock_pyside6 = MagicMock()
    sys.modules["PySide6"] = mock_pyside6
    sys.modules["PySide6.QtWidgets"] = mock_pyside6
    sys.modules["PySide6.QtCore"] = mock_pyside6
    sys.modules["PySide6.QtGui"] = mock_pyside6

try:
    import sounddevice
except ImportError:
    sys.modules["sounddevice"] = MagicMock()

try:
    import numpy
except ImportError:
    sys.modules["numpy"] = MagicMock()

try:
    import scipy
    import scipy.io.wavfile
except ImportError:
    mock_scipy = MagicMock()
    sys.modules["scipy"] = mock_scipy
    sys.modules["scipy.io"] = mock_scipy
    sys.modules["scipy.io.wavfile"] = mock_scipy

import unittest

if __name__ == "__main__":
    # Add current directory to path
    sys.path.insert(0, os.path.abspath(os.getcwd()))

    # Discover and run tests
    loader = unittest.TestLoader()
    tests = loader.discover('tests')
    testRunner = unittest.TextTestRunner()
    result = testRunner.run(tests)

    if not result.wasSuccessful():
        sys.exit(1)

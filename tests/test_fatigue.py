import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock Volume rule
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amp", "min": 0, "max": 1000, "pad": 4}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_noise(self):
        """Test that heat builds up and noise (0.9x) is applied above 5.0."""
        # amp=450 -> gain = 0.1 + 450/500 = 1.0
        # Gains:
        # 1: amp=450, gain=1.0. heat=1.0
        # 2: amp=451, gain=1.002. heat=2.002
        # 3: amp=452, gain=1.004. heat=3.006
        # 4: amp=453, gain=1.006. heat=4.012
        # 5: amp=454, gain=1.008. heat=5.02. Noise active for THIS item.
        # 6: amp=455, gain=1.01. heat=6.03. Noise active for THIS item.
        with open(self.input_file, 'w') as f:
            for i in range(6):
                amp = 450 + i
                f.write(f"VOL{amp:04d}\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 5.53, places=2)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            # Item 4 (amp=454) should have penalty (processed at 5.02)
            self.assertAlmostEqual(data[4]['parsed']['amp'], 454 * 0.9)
            # Item 5 (amp=455) should have penalty (processed at 6.03)
            self.assertAlmostEqual(data[5]['parsed']['amp'], 455 * 0.9)

    def test_thermal_overload(self):
        """Test that system refuses processing above 10.0 heat."""
        # amp=950 -> gain = 0.1 + 950/500 = 2.0
        with open(self.input_file, 'w') as f:
            for i in range(6):
                amp = 950 + i
                f.write(f"VOL{amp:04d}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Gains:
        # 1: gain=2.0. heat=2.0
        # 2: gain=2.002. heat=4.002
        # 3: gain=2.004. heat=6.006 (Noise active)
        # 4: gain=2.006. heat=8.012 (Noise active)
        # 5: gain=2.008. heat=10.02 (OVERLOAD)

        # Dissipation: 8.012 - 0.5 = 7.512
        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 7.512, places=3)

    def test_passive_dissipation(self):
        """Test that heat dissipates even when no DNA is processed."""
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 2.0}, f)

        with open(self.input_file, 'w') as f:
            pass

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 1.5)

if __name__ == '__main__':
    unittest.main()

import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, NOISE_THRESHOLD, OVERLOAD_THRESHOLD

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

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """Verify that processing DNA strings increases system heat."""
        # Use a unique string to avoid idempotency hit from other tests if they run in same process
        # though setUp should handle it via temp dir.
        with open(self.input_file, 'w') as f:
            f.write("VOL111\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            # Base (0.1) + Volume Penalty (0.2) = 0.3
            self.assertAlmostEqual(state['system_heat'], 0.3)

    def test_thermal_noise_application(self):
        """Verify that noise is applied when heat exceeds threshold."""
        # Set heat just below threshold
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": NOISE_THRESHOLD + 0.1, "last_run_timestamp": time.time()}, f)

        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            # Original was 100, should be 90 now (100 * 0.9)
            self.assertEqual(data[0]['parsed']['level'], 90)

    def test_thermal_overload_refusal(self):
        """Verify that processing is refused when heat exceeds safety limit."""
        # Set heat to the threshold
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": OVERLOAD_THRESHOLD, "last_run_timestamp": time.time()}, f)

        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_cooling_cycle(self):
        """Verify that heat dissipates over time."""
        # Set high heat in the past
        past_time = time.time() - 1500 # 1500 seconds ago
        # 1500 * 0.0083 = 12.45
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 5.0, "last_run_timestamp": past_time}, f)

        # Remove input file to test missing file cooling
        if os.path.exists(self.input_file):
            os.remove(self.input_file)

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            # Cooling rate is 0.0083/s. 1000s * 0.0083 = 8.3.
            # 5.0 - 8.3 should be 0.0
            self.assertEqual(state['system_heat'], 0.0)

    def test_idempotency_no_heat_gain(self):
        """Verify that skipped (deduplicated) items do not add heat."""
        dna = "VOL222"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch() # First run adds 0.3 heat

        with open(self.state_file, 'r') as f:
            heat_after_first = json.load(f)['system_heat']

        # We need to make sure cooling doesn't interfere, so we "mock" the time
        with open(self.state_file, 'r') as f:
            state = json.load(f)
        state['last_run_timestamp'] = time.time() + 100 # Future time to prevent cooling
        with open(self.state_file, 'w') as f:
            json.dump(state, f)

        run_batch() # Second run should skip and NOT add heat

        with open(self.state_file, 'r') as f:
            heat_after_second = json.load(f)['system_heat']

        # Since last_run_timestamp is in future, cooling might actually increase heat if not careful
        # but max(0, heat - cooling) where cooling is negative means heat - negative = heat + positive.
        # Wait, cooling = elapsed * rate. If elapsed is negative, cooling is negative.
        # system_heat = max(0.0, heat - negative) = heat + positive.
        # Let's just set last_run_timestamp to NOW.

        # Reset and retry with exact time
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 0.5, "last_run_timestamp": time.time()}, f)

        run_batch() # Should skip dna (already in ledger) and 0.5 should remain 0.5

        with open(self.state_file, 'r') as f:
            # We use a delta because a tiny bit of time might pass
            self.assertAlmostEqual(json.load(f)['system_heat'], 0.5, places=3)

if __name__ == '__main__':
    unittest.main()

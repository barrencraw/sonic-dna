import unittest
import os
import shutil
import tempfile
import json
import time
from unittest.mock import patch, MagicMock
from utils.dna_ui import (
    main as run_batch,
    load_system_state,
    save_system_state,
    ThermalOverloadError,
    MAX_HEAT,
    NOISE_THRESHOLD
)

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

        # Mock Volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amp", "min": 0, "max": 1000, "pad": 4}
                }
            }, f)

        # Mock other rule
        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity",
                "prefix": "CLR",
                "subvars": {
                    "val": {"description": "val", "min": 0, "max": 100, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """Test that heat increases with processing."""
        with open(self.input_file, 'w') as f:
            f.write("VOL0500\n") # +0.3
            f.write("CLR050\n")  # +0.1

        run_batch()

        state = load_system_state(self.state_file)
        self.assertAlmostEqual(state["system_heat"], 0.4, places=2)

    def test_cooling(self):
        """Test that heat decreases over time."""
        save_system_state(self.state_file, {"system_heat": 5.0, "last_update": time.time() - 120})

        # Run batch with empty input to trigger cooling
        with open(self.input_file, 'w') as f:
            pass

        run_batch()

        state = load_system_state(self.state_file)
        # 5.0 - (0.0083 * 120) = 5.0 - 0.996 = 4.004
        self.assertLess(state["system_heat"], 5.0)
        self.assertAlmostEqual(state["system_heat"], 4.0, places=1)

    def test_thermal_noise(self):
        """Test that noise is applied when heat > 7.0."""
        save_system_state(self.state_file, {"system_heat": 7.5, "last_update": time.time()})

        with open(self.input_file, 'w') as f:
            f.write("CLR050\n") # Result: 50 * 0.9 = 45

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(data[0]['parsed']['val'], 45.0)

    def test_thermal_overload(self):
        """Test that system refuses batch when heat > 10.0."""
        save_system_state(self.state_file, {"system_heat": 9.9, "last_update": time.time()})

        with open(self.input_file, 'w') as f:
            f.write("VOL0500\n") # +0.3 -> 10.2 > 10.0

        run_batch()

        # Ledger should NOT have the item because batch was aborted before commit
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        if os.path.exists(ledger_path):
            with open(ledger_path, 'r') as f:
                ledger = json.load(f)
                self.assertNotIn("VOL0500", ledger)

        state = load_system_state(self.state_file)
        self.assertGreater(state["system_heat"], 9.9) # Should have increased slightly due to stress

    def test_idempotency_with_heat(self):
        """Test that already processed items don't add heat again."""
        # First run
        with open(self.input_file, 'w') as f:
            f.write("CLR050\n")
        run_batch()

        state1 = load_system_state(self.state_file)
        h1 = state1["system_heat"]

        # Second run with same item
        run_batch()
        state2 = load_system_state(self.state_file)
        h2 = state2["system_heat"]

        # Should be same (ignoring tiny cooling if it happened fast)
        self.assertAlmostEqual(h1, h2, places=3)

if __name__ == '__main__':
    unittest.main()

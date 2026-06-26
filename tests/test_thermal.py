import unittest
import os
import json
import time
import shutil
import tempfile
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE_PER_SEC

class TestThermalDebt(unittest.TestCase):
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
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "vol", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """Verify that processing items increases system heat."""
        # 10 items should add 50 heat
        with open(self.input_file, 'w') as f:
            for i in range(10):
                f.write(f"V{i:02d}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state["system_heat"], 50.0)

    def test_thermal_lockout(self):
        """Verify that exceeding MAX_HEAT triggers lockout."""
        # 21 items * 5 = 105 heat (MAX=100)
        with open(self.input_file, 'w') as f:
            for i in range(21):
                f.write(f"V{i:02d}\n")

        # First run to reach threshold and interrupt
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            # Should have processed 21 items, heat = 105.0
            self.assertEqual(state["system_heat"], 105.0)
            self.assertEqual(len(state["ledger"]), 21)

        # Second run should be refused immediately
        with open(self.input_file, 'w') as f:
            f.write("V99\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_cooling_logic(self):
        """Verify that heat dissipates over time."""
        # Set initial heat to 50
        initial_time = time.time() - 60 # 60 seconds ago
        state = {
            "system_heat": 50.0,
            "last_processed_timestamp": initial_time,
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 60s * 0.5 units/s = 30 units cooling. 50 - 30 = 20 heat.
        # Process 1 item: 20 + 5 = 25 heat.
        with open(self.input_file, 'w') as f:
            f.write("V01\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            # Due to execution time, it might be slightly less than 25, but around that.
            self.assertLessEqual(state["system_heat"], 25.0)
            self.assertGreater(state["system_heat"], 20.0)

    def test_idempotency_no_heat_drain(self):
        """Verify that idempotency hits do not add heat."""
        with open(self.input_file, 'w') as f:
            f.write("V01\n")

        run_batch() # +5 heat

        with open(self.ledger_path, 'r') as f:
            heat1 = json.load(f)["system_heat"]

        run_batch() # Should skip, no heat added

        with open(self.ledger_path, 'r') as f:
            heat2 = json.load(f)["system_heat"]

        # heat2 should be slightly less than heat1 due to tiny cooling between calls
        self.assertLessEqual(heat2, heat1)
        self.assertGreater(heat2, heat1 - 1.0)

if __name__ == '__main__':
    unittest.main()

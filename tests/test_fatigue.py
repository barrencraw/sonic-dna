import unittest
import os
import shutil
import tempfile
import json
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
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

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
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
        """Verify that heat increases as sequences are processed."""
        num_seqs = 3
        with open(self.input_file, 'w') as f:
            for i in range(num_seqs):
                f.write(f"V{i:03}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            expected_heat = num_seqs * HEAT_PER_SEQ
            self.assertAlmostEqual(state['system_heat'], expected_heat)

    def test_thermal_lockout(self):
        """Verify that system raises ThermalOverloadError when MAX_HEAT is exceeded."""
        # Calculate how many sequences will exceed MAX_HEAT
        num_seqs = int(MAX_HEAT // HEAT_PER_SEQ) + 1

        with open(self.input_file, 'w') as f:
            for i in range(num_seqs):
                f.write(f"V{i:03}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check that some sequences were processed before lockout
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            processed_count = len(state['ledger'])
            self.assertEqual(processed_count, num_seqs - 1)
            self.assertAlmostEqual(state['system_heat'], (num_seqs - 1) * HEAT_PER_SEQ)

    def test_heat_dissipation(self):
        """Verify that heat dissipates over time."""
        # 1. Generate some heat
        with open(self.input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            initial_heat = state['system_heat']
            self.assertEqual(initial_heat, HEAT_PER_SEQ)

        # 2. Wait for a short duration
        wait_time = 1.5
        time.sleep(wait_time)

        # 3. Trigger dissipation (can be an empty run)
        with open(self.input_file, 'w') as f:
            pass # Empty file
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            expected_heat = max(0.0, initial_heat - (wait_time * COOLING_RATE))
            # Use a slightly larger delta because of time.sleep imprecision and processing time
            self.assertAlmostEqual(state['system_heat'], expected_heat, delta=0.5)
            self.assertTrue(state['system_heat'] < initial_heat)

if __name__ == '__main__':
    unittest.main()

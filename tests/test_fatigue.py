import unittest
import os
import shutil
import tempfile
import json
import time
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, DNAStatus, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

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
        """Verify that heat accumulates per processed sequence."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("V100\nV200\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            # 2 sequences * 5.0 heat = 10.0
            self.assertEqual(data['system_heat'], 10.0)
            self.assertEqual(len(data['ledger']), 2)

    def test_thermal_lockout(self):
        """Verify that processing stops and raises ThermalOverloadError when threshold is reached."""
        # Threshold is 100, each sequence is 5.
        # Need 21 sequences to exceed 100.
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            for i in range(25):
                f.write(f"V{i:03d}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            # Should have processed 20 successfully (100 heat)
            # The 21st should be REFUSED
            self.assertEqual(data['system_heat'], 100.0)
            self.assertEqual(len(data['ledger']), 21)

            refused_count = sum(1 for v in data['ledger'].values() if v['terminal_outcome'] == DNAStatus.REFUSED.value)
            self.assertEqual(refused_count, 1)

    def test_dissipation(self):
        """Verify that heat dissipates over time."""
        # Setup initial heat
        initial_ledger = {
            "system_heat": 50.0,
            "last_processed_timestamp": int(time.time()) - 10, # 10 seconds ago
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(initial_ledger, f)

        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("V100\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            # 50.0 - (10s * 0.5/s) + 5.0 (for V100) = 45.0 + 5.0 = 50.0
            self.assertEqual(data['system_heat'], 50.0)

    def test_idempotency_retry_refused(self):
        """Verify that REFUSED items are retried, while SUCCESS items are skipped."""
        # 1. Process one item to SUCCESS
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        # 2. Force a REFUSED state in ledger
        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        data['ledger']["V200"] = {
            "terminal_outcome": DNAStatus.REFUSED.value,
            "timestamp": "some-time"
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(data, f)

        # 3. Try to process both
        with open(input_file, 'w') as f:
            f.write("V100\nV200\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['ledger']["V100"]["terminal_outcome"], DNAStatus.SUCCESS.value)
            self.assertEqual(data['ledger']["V200"]["terminal_outcome"], DNAStatus.SUCCESS.value)
            # Heat should be: 5 (from first run V100) + 5 (from second run V200) = 10.0
            # (Assuming negligible time passed for dissipation)
            self.assertAlmostEqual(data['system_heat'], 10.0, delta=0.5)

if __name__ == '__main__':
    unittest.main()

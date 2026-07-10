import unittest
import os
import shutil
import tempfile
import json
import time
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a rule file
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_lockout(self):
        # HEAT_PER_SEQ = 20, MAX_HEAT = 100
        # 5 sequences should be OK, 6th should trigger lockout
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            for i in range(10):
                f.write(f"V{i:03d}\n")

        # Now we EXPECT ThermalOverloadError to be raised to the caller
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            state = json.load(f)

        # 5 items should be processed
        self.assertEqual(len(state['ledger']), 5)
        self.assertEqual(state['system_heat'], 100.0)

    def test_heat_dissipation(self):
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Pre-set high heat in the past
        past_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)).isoformat()
        with open(ledger_path, 'w') as f:
            json.dump({
                'system_heat': 50.0,
                'last_processed_timestamp': past_time,
                'ledger': {}
            }, f)

        # COOLING_RATE = 2.0. 10 seconds = 20 units dissipated. 50 - 20 = 30.
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("V100\n")

        run_batch()

        with open(ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be (50 - 20) + 20 = 50
        self.assertAlmostEqual(state['system_heat'], 50.0, delta=1.0)

    def test_dissipation_without_processing(self):
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        past_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)).isoformat()
        with open(ledger_path, 'w') as f:
            json.dump({
                'system_heat': 50.0,
                'last_processed_timestamp': past_time,
                'ledger': {'some': 'data'}
            }, f)

        # No input file or empty input file
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            pass

        run_batch()

        with open(ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be 50 - 20 = 30
        self.assertAlmostEqual(state['system_heat'], 30.0, delta=1.0)
        self.assertEqual(state['ledger'], {'some': 'data'})

if __name__ == '__main__':
    unittest.main()

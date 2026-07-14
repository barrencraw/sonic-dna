import os
import json
import shutil
import unittest
import time
import tempfile
import datetime
from utils.dna_ui import run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ

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
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a rule
        with open(os.path.join(self.rules_dir, 'rules_Vol.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {"v": {"description": "v", "min": 0, "max": 9, "pad": 1}}
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """Verify that heat increases per sequence."""
        with open(self.input_file, 'w') as f:
            f.write("VOL1\nVOL2\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # 2 sequences processed = 40.0 heat
        self.assertAlmostEqual(state['system_heat'], HEAT_PER_SEQ * 2)

    def test_thermal_lockout(self):
        """Verify that reaching MAX_HEAT stops processing and raises ThermalOverloadError."""
        # Enough sequences to exceed MAX_HEAT (100.0 / 20.0 = 5 sequences)
        with open(self.input_file, 'w') as f:
            for i in range(10):
                f.write(f"VOL{i}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should stop exactly at MAX_HEAT
        self.assertEqual(state['system_heat'], MAX_HEAT)
        # Should have processed exactly 5 items (5 * 20 = 100)
        self.assertEqual(len(state['ledger']), 5)

    def test_heat_dissipation(self):
        """Verify that heat dissipates over time."""
        # 1. Add heat
        with open(self.input_file, 'w') as f:
            f.write("VOL1\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        initial_heat = state['system_heat']
        self.assertEqual(initial_heat, 20.0)

        # 2. Mock time passing in the ledger
        # We'll set last_update to 5 seconds ago. COOLING_RATE is 2.0/s, so 10.0 heat should dissipate.
        past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=5)
        state['last_update'] = past_time.isoformat()
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 3. Run idle batch (empty input)
        with open(self.input_file, 'w') as f:
            pass
        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # 20.0 - (5 * 2.0) = 10.0
        self.assertAlmostEqual(new_state['system_heat'], 10.0, delta=0.5)

    def test_idempotency_no_heat(self):
        """Verify that skipped items (idempotent) do not add heat."""
        # 1. Process once
        with open(self.input_file, 'w') as f:
            f.write("VOL1\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        heat_after_one = state['system_heat']

        # 2. Process same item again
        with open(self.input_file, 'w') as f:
            f.write("VOL1\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Heat should be same or less (due to minor dissipation), not increased by HEAT_PER_SEQ
        self.assertLessEqual(new_state['system_heat'], heat_after_one)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import time
import tempfile
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE, ThermalOverloadError

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

        # Mock a rule file
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
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
        # 1 sequence = HEAT_PER_SEQ heat
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], HEAT_PER_SEQ)
        self.assertIn("VOL100", state['ledger'])

    def test_heat_dissipation(self):
        # Initial heat
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")
        run_batch()

        # Manually backdate the last_update_timestamp in the ledger
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Backdate by 10 seconds
        from utils.dna_ui import format_timestamp, get_utc_now
        import datetime
        backdated = get_utc_now() - datetime.timedelta(seconds=10)
        state['last_update_timestamp'] = format_timestamp(backdated)

        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Run empty batch to trigger dissipation
        with open(self.input_file, 'w') as f:
            f.write("")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        expected_heat = max(0.0, HEAT_PER_SEQ - (10 * COOLING_RATE))
        self.assertAlmostEqual(new_state['system_heat'], expected_heat, places=1)

    def test_thermal_lockout(self):
        # Calculate how many sequences it takes to exceed MAX_HEAT
        count = int(MAX_HEAT // HEAT_PER_SEQ) + 1

        dnas = [f"VOL{str(i).zfill(3)}" for i in range(count)]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        # This should raise ThermalOverloadError
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Verify some were processed but not all
        processed_count = len(state['ledger'])
        self.assertLess(processed_count, count)
        self.assertGreater(processed_count, 0)
        self.assertGreaterEqual(state['system_heat'], MAX_HEAT - HEAT_PER_SEQ)

    def test_idempotency_with_heat(self):
        # Processing a known DNA string should NOT add heat
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_heat']

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)
        heat2 = state2['system_heat']

        # Heat should be same or less (dissipation), definitely not increased by HEAT_PER_SEQ
        self.assertLessEqual(heat2, heat1)

if __name__ == '__main__':
    unittest.main()

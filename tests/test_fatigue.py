import unittest
import os
import json
import shutil
import tempfile
import time
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

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {"level": {"description": "volume", "min": 0, "max": 999, "pad": 3}}
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_thermal_accumulation_and_lockout(self):
        # MAX_HEAT = 100, HEAT_PER_SEQ = 20. 6 sequences should trigger lockout.
        sequences = [f"V{str(i).zfill(3)}" for i in range(10)]
        with open(self.input_file, 'w') as f:
            for s in sequences:
                f.write(s + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify ledger state
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
            # 5 successful * 20 = 100
            self.assertAlmostEqual(state['system_heat'], 100.0, delta=0.5)

            # 5 should be success, 1 refused
            success_count = sum(1 for v in state['ledger'].values() if v['terminal_outcome'] == 'success')
            refused_count = sum(1 for v in state['ledger'].values() if v['terminal_outcome'] == 'refused')
            self.assertEqual(success_count, 5)
            self.assertEqual(refused_count, 1)

    def test_thermal_dissipation(self):
        # Manually set high heat in ledger
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        past = now - datetime.timedelta(seconds=10)

        state = {
            "system_heat": 100.0,
            "last_processed_timestamp": past.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        }

        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        with open(self.input_file, 'w') as f:
            f.write("V111\n")

        # Cooling rate is 2.0/s. In 10s, it should dissipate 20 units.
        # 100 - 20 = 80. Adding one seq (20) makes it 100.
        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)
            # Calculation: 100 - (10+small_delay)*2 + 20
            # If 10.5s passed: 100 - 21 + 20 = 99
            self.assertAlmostEqual(new_state['system_heat'], 100.0, delta=2.0)

if __name__ == '__main__':
    unittest.main()

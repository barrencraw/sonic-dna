import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Link rules directory to the test dir
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        # We need the actual rules from the project
        src_rules = os.path.join(os.getcwd(), 'rules')
        shutil.copytree(src_rules, self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_volume_increases_heat(self):
        dna = "VOL05000750712" # amp=500 -> heat_gain=5.0
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 5.0)

    def test_clarity_penalized_by_heat(self):
        vol_dna = "VOL05000750712" # amp=500 -> heat_gain=5.0
        cla_dna = "CLAZN0900015"   # noise_floor=90

        with open(self.input_file, 'w') as f:
            f.write(vol_dna + "\n" + cla_dna + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.output_json, 'r') as f:
            results = json.load(f)

        # CLA should be second
        cla_result = next(r for r in results if r['dna'] == cla_dna)
        # penalty = int(5.0) = 5. noise_floor should be 90 - 5 = 85.
        self.assertEqual(cla_result['parsed']['noise_floor']['value'], 85)
        self.assertEqual(cla_result['consequence'], "THERMAL_NOISE_PENALTY")

    def test_clarity_refusal_at_high_heat(self):
        vol_dna = "VOL10000750712" # amp=1000 -> heat_gain=10.0
        cla_dna = "CLAZN0900015"

        with open(self.input_file, 'w') as f:
            f.write(vol_dna + "\n" + cla_dna + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.output_json, 'r') as f:
            results = json.load(f)

        cla_result = next(r for r in results if r['dna'] == cla_dna)
        self.assertIn('error', cla_result)
        self.assertEqual(cla_result['refusal'], "THERMAL_OVERLOAD")

    def test_fatigue_idempotency(self):
        dna = "VOL05000750712" # amp=500 -> heat_gain=5.0

        # First run
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 5.0)

        # Second run with same DNA
        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        # Heat should NOT have increased again
        self.assertAlmostEqual(state['system_heat'], 5.0)

if __name__ == '__main__':
    unittest.main()

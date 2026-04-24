import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch, load_system_state

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test data
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Link or copy rules to the test directory
        # We'll just use the real rules folder
        self.real_rules_dir = os.path.abspath('rules')
        os.symlink(self.real_rules_dir, os.path.join(self.test_dir, 'rules'))

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        path = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(path, 'w', encoding='utf-8') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def test_heat_accumulation_and_cooling(self):
        state_path = os.path.join(self.test_dir, 'data', 'system_state.json')

        # 1. First run: Natural cooling applies to empty state (0.0 -> 0.0)
        # Then Volume DNA (amp=0890 -> 890/100 = +8.9)
        # Total heat: 0.0 - 1.0 (clamped to 0) + 8.9 = 8.9
        self.write_dna(["VOL08900750712"])
        run_batch(data_dir=self.test_dir)

        state = load_system_state(state_path)
        self.assertAlmostEqual(state["system_heat"], 8.9)

        # 2. Second run: Natural cooling (8.9 -> 7.9)
        # Then another Volume DNA (amp=0200 -> +2.0)
        # Total heat: 7.9 + 2.0 = 9.9
        self.write_dna(["VOL02000500000"])
        run_batch(data_dir=self.test_dir)

        state = load_system_state(state_path)
        self.assertAlmostEqual(state["system_heat"], 9.9)

    def test_clarity_penalty(self):
        state_path = os.path.join(self.test_dir, 'data', 'system_state.json')

        # Set heat to 5.0
        with open(state_path, 'w') as f:
            json.dump({"system_heat": 6.0}, f) # 6.0 - 1.0 (cooling) = 5.0

        # CLAZN0900015 (N090 -> noise floor 90)
        # Heat 5.0 -> penalty 5
        # Expected noise floor: 90 - 5 = 85
        self.write_dna(["CLAZN0900015"])
        run_batch(data_dir=self.test_dir)

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            results = json.load(f)

        # Find the Clarity result
        cla_result = next(r for r in results if r['dna'] == "CLAZN0900015")
        self.assertEqual(cla_result['parsed']['noise_floor']['value'], 85)

    def test_thermal_overload_refusal(self):
        state_path = os.path.join(self.test_dir, 'data', 'system_state.json')

        # Set heat to 12.0
        with open(state_path, 'w') as f:
            json.dump({"system_heat": 12.0}, f) # 12.0 - 1.0 = 11.0

        self.write_dna(["CLAZN0900015"])
        run_batch(data_dir=self.test_dir)

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            results = json.load(f)

        cla_result = next(r for r in results if r['dna'] == "CLAZN0900015")
        self.assertIn("Thermal Overload", cla_result['error'])

        ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn("error: Thermal Overload", ledger["CLAZN0900015"]['terminal_outcome'])

if __name__ == '__main__':
    unittest.main()

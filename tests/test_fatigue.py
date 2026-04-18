import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as dna_main

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test data
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Mock project structure for rules
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        shutil.copytree('rules', self.rules_dir)

        # Change to test_dir so os.getcwd() works as expected for dna_main
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w', encoding='utf-8') as f:
            for dna in dna_list:
                f.write(dna + '\n')

    def test_heat_accumulation_and_penalty(self):
        # 1. Process a Volume DNA string to increase heat.
        # VOL08900750712: amp=890 -> heat gain = 8.90
        # Natural cooling at start: 0.0 -> 0.0
        # Resulting heat: 8.90
        self.write_dna(["VOL08900750712"])
        dna_main()

        state_path = os.path.join(self.test_dir, 'data', 'system_state.json')
        with open(state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 8.90)

        # 2. Process a Clarity DNA string and check for penalty.
        # Natural cooling at start: 8.90 -> 7.90
        # Penalty: int(7.90) = 7
        # CLAZN0900015: noise_floor N090 -> 90. Penalized: 90 - 7 = 83.
        self.write_dna(["CLAZN0900015"])
        dna_main()

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            parsed = json.load(f)

        # Find the Clarity entry
        cla_entry = next(e for e in parsed if e.get('rule') == 'Clarity')
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 83)
        self.assertIn("Thermal noise penalty", cla_entry['CONSEQUENCE_APPLIED'])

    def test_thermal_overload_refusal(self):
        # 1. Accumulate heat above 10.0
        # VOL10000750712: amp=1000 -> heat gain = 10.0
        # Run twice to be sure
        self.write_dna(["VOL10000750712"])
        dna_main()
        # Heat: 10.0

        self.write_dna(["VOL05000750712"]) # Different DNA to avoid idempotency hit
        dna_main()
        # Heat: 10.0 - 1.0 (cooling) + 5.0 = 14.0

        state_path = os.path.join(self.test_dir, 'data', 'system_state.json')
        with open(state_path, 'r') as f:
            state = json.load(f)
        self.assertGreater(state['system_heat'], 10.0)

        # 2. Process Clarity and check for refusal
        self.write_dna(["CLAZN0600015"]) # Different DNA
        dna_main()

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            parsed = json.load(f)

        cla_entry = next(e for e in parsed if e['dna'] == "CLAZN0600015")
        self.assertIn("error", cla_entry)
        self.assertIn("Thermal overload", cla_entry['REFUSAL_REASON'])
        self.assertIn("Cease high-amplitude operations", cla_entry['NEXT_ACTION_HINT'])

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as dna_main

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'raw')
        self.output_dir = os.path.join(self.test_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.test_dir, 'system_state.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_increase_and_cooling(self):
        # VOL0900... -> amp=900
        # Expected heat increase: 900/1000 = 0.9.
        # But wait, every DNA processed cools by 0.1 first.
        # Initial heat 0.0 -> cooling (0.0) -> increase (0.9) -> final heat 0.9.
        with open(self.input_file, 'w') as f:
            f.write("VOL09000750712\n")

        dna_main(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 0.9)

        # Process another VOL0900
        # Start at 0.9 -> cooling (0.8) -> increase (0.9) -> final 1.7
        with open(self.input_file, 'w') as f:
            f.write("VOL09000750712\n") # This is duplicate DNA, but we need to bypass ledger to re-run
            # Actually, toSequence.txt is cleared, but ledger persists.
            # Use different DNA to ensure it's processed
            f.write("VOL09000750713\n")

        dna_main(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 1.7)

    def test_clarity_penalty(self):
        # 1. Increase heat to 5.0
        # We need roughly 6 DNA strings of VOL0900 to get near 5.0
        # 0 -> 0.9 (1)
        # 0.9 -> 1.7 (2)
        # 1.7 -> 2.5 (3)
        # 2.5 -> 3.3 (4)
        # 3.3 -> 4.1 (5)
        # 4.1 -> 4.9 (6)
        with open(self.input_file, 'w') as f:
            for i in range(6):
                f.write(f"VOL090007507{10+i}\n")

        dna_main(data_dir=self.test_dir)

        # 2. Process Clarity DNA
        # CLAZN0900015 -> noise_floor = 90
        # Heat is 4.9. Penalty = int(4.9) = 4.
        # New noise = 90 - 4 = 86.
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        dna_main(data_dir=self.test_dir)

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            results = json.load(f)

        # Find the Clarity result
        cla_result = next(r for r in results if r['rule'] == 'Clarity')
        self.assertEqual(cla_result['parsed']['noise_floor']['value'], 86)

    def test_thermal_overload(self):
        # 1. Increase heat to >= 10.0
        # 0 -> 0.9 (1)
        # ...
        # each step adds 0.8 net heat.
        # 13 steps * 0.8 = 10.4
        with open(self.input_file, 'w') as f:
            for i in range(13):
                f.write(f"VOL090007507{10+i}\n")

        dna_main(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertGreaterEqual(state['system_heat'], 10.0)

        # 2. Process Clarity DNA -> Should Fail
        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900016\n")

        dna_main(data_dir=self.test_dir)

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            results = json.load(f)

        # Find the Clarity result
        cla_result = next(r for r in results if r['dna'] == 'CLAZN0900016')
        self.assertIn("thermal overload", cla_result.get('error', ''))

if __name__ == '__main__':
    unittest.main()

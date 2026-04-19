#!/usr/bin/env python3
import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy real rules to temp dir
        shutil.copytree('rules', self.rules_dir, dirs_exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w', encoding='utf-8') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def test_heat_accumulation(self):
        # VOL0500... -> amp=500 -> heat gain = 5.0.
        # But wait, there is natural cooling of -1.0 at start.
        # Initial heat 0 -> cooling -> 0.
        # Process VOL -> heat 5.0.
        self.write_dna(["VOL05000500012"])
        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

    def test_clarity_penalty(self):
        # 1. Generate heat
        self.write_dna(["VOL05000500012"]) # Heat = 5.0
        run_batch(data_dir=self.test_dir)

        # 2. Process Clarity
        # CLAZN0900015 -> noise_floor = 90
        # Cooling -1.0 -> heat = 4.0
        # Penalty = int(4.0) = 4
        # New noise_floor = 90 - 4 = 86
        self.write_dna(["CLAZN0900015"])
        run_batch(data_dir=self.test_dir)

        parsed_json_path = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(parsed_json_path, 'r') as f:
            parsed = json.load(f)

        # Find the clarity entry
        cla_entry = next(e for e in parsed if e.get('rule') == 'Clarity')
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 86)
        self.assertIn("Thermal noise added", cla_entry['consequence'])

    def test_clarity_refusal(self):
        # 1. Generate massive heat
        # VOL1000... -> amp=1000 -> heat gain = 10.0
        # Process two to be sure
        self.write_dna(["VOL10000500012", "VOL08000500012"])
        # cooling -1.0 -> heat = 0
        # process 1: heat = 10.0
        # process 2: heat = 18.0
        run_batch(data_dir=self.test_dir)

        # 2. Process Clarity
        # cooling -1.0 -> heat = 17.0
        # 17.0 > 10.0 -> Refusal
        self.write_dna(["CLAZN0900015"])
        run_batch(data_dir=self.test_dir)

        parsed_json_path = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(parsed_json_path, 'r') as f:
            parsed = json.load(f)

        cla_entry = next(e for e in parsed if e.get('dna') == 'CLAZN0900015')
        self.assertIn("error", cla_entry)
        self.assertIn("Thermal overload", cla_entry['error'])

    def test_idempotency_heat(self):
        # Process VOL twice (once in each batch)
        # Batch 1: cooling -1.0 (heat 0), VOL0500 -> heat 5.0
        self.write_dna(["VOL05000500012"])
        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state1 = json.load(f)
        self.assertEqual(state1['system_heat'], 5.0)

        # Batch 2: cooling -1.0 (heat 4.0), VOL0500 (skipped) -> heat remains 4.0
        self.write_dna(["VOL05000500012"])
        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state2 = json.load(f)
        self.assertEqual(state2['system_heat'], 4.0)

if __name__ == '__main__':
    unittest.main()

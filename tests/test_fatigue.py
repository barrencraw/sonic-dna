import os
import json
import csv
import shutil
import tempfile
import unittest
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_folder = os.path.join(self.test_dir, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        os.makedirs(self.raw_folder)
        os.makedirs(self.output_folder)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_penalty(self):
        # 1. Process high volume DNA to increase heat (amp=800 -> +8.0 heat)
        dna_vol = "VOL08000500510"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_vol + "\n")

        run_batch(self.test_dir)

        with open(self.state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 8.0)

        # 2. Process Clarity DNA and check noise floor penalty
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_cla + "\n")

        run_batch(self.test_dir) # 8.0 - 1.0 (cooling) = 7.0 heat penalty applied

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 83) # 90 - 7 = 83

        with open(self.state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 7.0)

    def test_thermal_overload_refusal(self):
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump({"system_heat": 12.0}, f)

        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_cla + "\n")

        run_batch(self.test_dir)

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertIn("error", cla_entry)
        self.assertIn("THERMAL_OVERLOAD", cla_entry['error'])
        self.assertIn("THERMAL_LOCKOUT", cla_entry['error'])

    def test_natural_cooling(self):
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump({"system_heat": 5.0}, f)

        dna = "VOL01000500510" # amp=100 -> +1.0 heat
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(self.test_dir) # 5.0 - 1.0 (cooling) + 1.0 (VOL) = 5.0

        with open(self.state_path, 'r', encoding='utf-8') as f:
            self.assertEqual(json.load(f)['system_heat'], 5.0)

        # Process a sequence that is already processed (deduped hit)
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(self.test_dir) # 5.0 - 1.0 (cooling) = 4.0

        with open(self.state_path, 'r', encoding='utf-8') as f:
            self.assertEqual(json.load(f)['system_heat'], 4.0)

    def test_idempotency_no_double_drain(self):
        dna_vol = "VOL08000500510" # amp=800 -> +8.0 heat
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_vol + "\n")

        run_batch(self.test_dir)

        with open(self.state_path, 'r', encoding='utf-8') as f:
            initial_heat = json.load(f)['system_heat']
        self.assertEqual(initial_heat, 8.0)

        # Run again with same DNA
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_vol + "\n")

        run_batch(self.test_dir)

        # Sequence was skipped due to deduplication, so heat cooled down to 7.0 instead of adding another 8.0
        with open(self.state_path, 'r', encoding='utf-8') as f:
            second_heat = json.load(f)['system_heat']
        self.assertEqual(second_heat, 7.0)

if __name__ == '__main__':
    unittest.main()

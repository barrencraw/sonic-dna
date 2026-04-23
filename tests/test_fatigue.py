import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_folder = os.path.join(self.test_dir, 'data', 'raw')
        self.output_folder = os.path.join(self.test_dir, 'data', 'output')
        os.makedirs(self.raw_folder)
        os.makedirs(self.output_folder)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.state_path = os.path.join(self.test_dir, 'data', 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Link rules
        os.symlink(os.path.join(os.getcwd(), 'rules'), os.path.join(self.test_dir, 'rules'))

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_cooling(self):
        # VOL0890... -> amp = 0890 (89.0%) -> heat += 8.9
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        # First batch: cooling max(0, 0 - 1.0) = 0, then +8.9 -> net heat 8.9
        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 8.9)

        # Second batch: Let's add a non-VOL string to trigger cooling.
        dna_fxa = "FXA000000000000T0000"
        with open(self.input_file, 'w') as f:
            f.write(dna_fxa + "\n")

        # Second batch: 8.9 - 1.0 = 7.9
        run_batch(data_dir=self.test_dir)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 7.9)

    def test_clarity_penalty(self):
        # 1. Set heat to 5.0
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 6.0}, f) # 6.0 - 1.0 (cooling) = 5.0

        dna_cla = "CLAZN0900015" # noise_floor = -90
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # penalty = int(5.0) = 5. noise_floor should be 90 - 5 = 85.
        self.assertEqual(data[0]['parsed']['noise_floor']['value'], 85)

    def test_clarity_refusal(self):
        # 1. Set heat to 12.0
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 11.1}, f) # 11.1 - 1.0 = 10.1

        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertIn("error", data[0])
        self.assertIn("thermal overload", data[0]['error'].lower())

    def test_idempotency_heat(self):
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch(data_dir=self.test_dir) # heat = 8.9

        with open(self.state_path, 'r') as f:
            heat1 = json.load(f)['system_heat']
        self.assertAlmostEqual(heat1, 8.9)

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch(data_dir=self.test_dir) # heat = 8.9 - 1.0 = 7.9 (deduped, so no gain)

        with open(self.state_path, 'r') as f:
            heat2 = json.load(f)['system_heat']

        self.assertLess(heat2, heat1)
        self.assertAlmostEqual(heat2, 7.9)

    def test_idempotency_no_output_overwrite(self):
        # 1. Process one DNA
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data1 = json.load(f)
        self.assertEqual(len(data1), 1)

        # 2. Run again with SAME DNA. new_processed_count will be 0.
        # It SHOULD NOT overwrite data1 with empty list.
        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data2 = json.load(f)
        self.assertEqual(len(data2), 1, "Output file was cleared but should have been preserved!")
        self.assertEqual(data2, data1)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch, Outcome

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

        # Copy rules
        for f in os.listdir('rules'):
            if f.endswith('.json'):
                shutil.copy(os.path.join('rules', f), self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_from_volume(self):
        # VOL0890... -> amp=0890 -> 8.9 heat
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        # Initial heat 0.0 -> cooling -1.0 -> max(0, -1) = 0.0 -> add 8.9 = 8.9
        self.assertEqual(state['system_heat'], 8.9)

    def test_clarity_penalty_applied(self):
        # First increase heat
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 6.0}, f)

        # CLA Z N090 0015
        dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Heat 6.0 -> cooling -1.0 = 5.0
        # Noise floor: N090 -> N(90-5) = N085
        # THD: 0015 + (5 * 10) = 0065

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        parsed = data[0]['parsed']
        self.assertEqual(parsed['noise_floor']['value'], 85)
        self.assertEqual(parsed['thd'], 65)

    def test_thermal_refusal(self):
        # Heat above threshold (10.0)
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 12.0}, f)

        dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Heat 12.0 -> cooling -1.0 = 11.0 (> 10.0 refusal)

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertIn("error", data[0])
        self.assertIn("Core temperature at 11.0U", data[0]['error'])

    def test_natural_cooling(self):
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 0.5}, f)

        # Just some neutral DNA to trigger batch
        dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        # 0.5 - 1.0 = -0.5 -> max(0, -0.5) = 0.0
        self.assertEqual(state['system_heat'], 0.0)

if __name__ == '__main__':
    unittest.main()

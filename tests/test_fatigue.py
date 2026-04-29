import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.test_dir, 'data', 'system_state.json')
        self.ledger_file = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        self.parsed_json = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Mock the working directory to our temp dir
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Ensure rules are available
        # The rules folder is expected at the project root
        shutil.copytree(os.path.join(self.old_cwd, 'rules'), os.path.join(self.test_dir, 'rules'))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(dna + '\n')

    def test_heat_accumulation_and_cooling(self):
        # 1. Start with 0 heat
        self.write_dna(['VOL05000000000']) # amp 500 -> heat gain 5.0
        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            # 0.0 (start) - 1.0 (cooling, max(0,...)) + 5.0 (gain) = 5.0
            self.assertEqual(state['system_heat'], 5.0)

        # 2. Natural cooling
        self.write_dna(['VOL00000000000']) # amp 0 -> heat gain 0.0
        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)
            # 5.0 (prev) - 1.0 (cooling) + 0.0 (gain) = 4.0
            self.assertEqual(state['system_heat'], 4.0)

    def test_clarity_degradation(self):
        # Set heat to 5.0
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 6.0}, f) # 6 - 1 (cooling) = 5.0

        self.write_dna(['CLAZN0900015'])
        run_batch()

        with open(self.parsed_json, 'r') as f:
            results = json.load(f)
            # Find the CLA entry
            cla_entry = next(r for r in results if r['dna'] == 'CLAZN0900015')
            parsed = cla_entry['parsed']
            # Heat was 5.0
            # THD increase: 5 * 10 = 50. Original 15 -> 65
            self.assertEqual(parsed['thd'], 65)
            # Noise floor decrease: 5. Original 90 -> 85
            self.assertEqual(parsed['noise_floor']['value'], 85)

    def test_thermal_overload_refusal(self):
        # Set heat to 11.1
        with open(self.state_file, 'w') as f:
            json.dump({'system_heat': 11.1}, f) # 11.1 - 1.0 = 10.1 (still > 10)

        self.write_dna(['CLAZN0900015'])
        run_batch()

        with open(self.parsed_json, 'r') as f:
            results = json.load(f)
            cla_entry = next(r for r in results if r['dna'] == 'CLAZN0900015')
            self.assertIn('REFUSAL_REASON', cla_entry['error'])
            self.assertIn('NEXT_ACTION_HINT', cla_entry['error'])

    def test_idempotency_heat(self):
        # Heat should only accumulate for NEW DNA
        self.write_dna(['VOL10000000000']) # Gain 10.0
        run_batch()

        with open(self.state_file, 'r') as f:
            h1 = json.load(f)['system_heat'] # 0 - 0 (max(0,0-1)) + 10 = 10.0
            self.assertEqual(h1, 10.0)

        # Run again with same DNA
        self.write_dna(['VOL10000000000'])
        run_batch()

        with open(self.state_file, 'r') as f:
            h2 = json.load(f)['system_heat'] # 10.0 - 1.0 (cooling) + 0 (deduped) = 9.0
            self.assertEqual(h2, 9.0)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import time
import tempfile
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for all test data
        self.test_dir = tempfile.TemporaryDirectory()
        self.data_folder = self.test_dir.name

        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Clean up the temporary directory
        self.test_dir.cleanup()

    def test_heat_accumulation_and_penalty(self):
        # 1. Process Volume DNA to generate heat
        # VOL + amp(1000) + lr(075) + sur(07) + head(12)
        vol_dna = "VOL10000750712"

        # 2. Process Clarity DNA
        cla_dna = "CLAZN0900015"

        with open(self.input_file, 'w') as f:
            f.write(f"{vol_dna}\n{cla_dna}\n")

        run_batch(custom_data_dir=self.data_folder)

        # Verify heat in state
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertGreaterEqual(state['system_heat'], 1.0)

        # Verify penalty in output
        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_result = next(item for item in data if item['dna'] == cla_dna)
        self.assertEqual(cla_result['parsed']['noise_floor']['value'], 91)
        self.assertEqual(cla_result['parsed']['noise_floor']['fatigue_penalty'], 1)

    def test_heat_dissipation(self):
        # 1. Set initial heat
        initial_state = {
            "system_heat": 5.0,
            "last_updated": time.time() - 15.0
        }
        with open(self.state_path, 'w') as f:
            json.dump(initial_state, f)

        cla_dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(cla_dna + "\n")

        run_batch(custom_data_dir=self.data_folder)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 3.5, delta=0.2)

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(data[0]['parsed']['noise_floor']['value'], 93)

    def test_refusal_threshold(self):
        # 1. Set heat above threshold (10.0)
        initial_state = {
            "system_heat": 12.0,
            "last_updated": time.time()
        }
        with open(self.state_path, 'w') as f:
            json.dump(initial_state, f)

        cla_dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(cla_dna + "\n")

        run_batch(custom_data_dir=self.data_folder)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger[cla_dna]['terminal_outcome'], 'skipped: thermal limit')

        # Verify it's NOT in the parsed output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 0)

if __name__ == '__main__':
    unittest.main()

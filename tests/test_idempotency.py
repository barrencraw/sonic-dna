import os
import json
import shutil
import unittest
import time
import tempfile
from utils.dna_ui import run_batch

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # Create a completely isolated sandbox for each test
        self.test_dir = tempfile.mkdtemp()
        self.data_folder = os.path.join(self.test_dir, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        os.makedirs(self.rules_folder, exist_ok=True)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_heat': 0.0, 'last_update': ''}, f)

        # Mock a rule in the isolated rules folder
        with open(os.path.join(self.rules_folder, 'rules_Vol.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {"v": {"description": "v", "min": 0, "max": 9999999999, "pad": 10}}
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_double_invocation_same_key(self):
        dna = "VOL0890075071"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        ledger = state.get('ledger', state)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should NOT have added a second entry for the same DNA")

    def test_mixed_duplicates(self):
        dna1 = "VOL0890075071"
        dna2 = "VOL0000000000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna1}\n{dna2}\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 2, "Should have exactly 2 entries")
        dnas = [entry['dna'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

    def test_retry_after_transient_failure(self):
        dna = "VOL0890075071"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        ledger = state.get('ledger', state)
        self.assertIn(dna, ledger)

        with open(self.json_output, 'w') as f:
            f.write("CORRUPTED")

        new_dna = "VOL0000000000"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], new_dna)

if __name__ == '__main__':
    unittest.main()

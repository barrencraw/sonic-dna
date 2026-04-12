import os
import json
import shutil
import unittest
import time
import tempfile
from utils.dna_ui import main as run_batch

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for all test data
        self.test_dir = tempfile.TemporaryDirectory()
        self.data_folder = self.test_dir.name

        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Clean up the temporary directory
        self.test_dir.cleanup()

    def test_double_invocation_same_key(self):
        # DNA for Volume (prefix 'VOL')
        dna = "VOL08900750712"

        # 1. First invocation
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(custom_data_dir=self.data_folder)

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

        # 2. Second invocation with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(custom_data_dir=self.data_folder)

        # Verify no duplicate entry in output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should NOT have added a second entry for the same DNA")

    def test_mixed_duplicates(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna1}\n{dna2}\n")

        run_batch(custom_data_dir=self.data_folder)

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        # It should process dna1 (once) and dna2 (once)
        self.assertEqual(len(data), 2, "Should have exactly 2 entries")
        dnas = [entry['dna'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

    def test_retry_after_transient_failure(self):
        dna = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(custom_data_dir=self.data_folder) # Success

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

        # Let's test if it handles corrupted output file gracefully.
        with open(self.json_output, 'w') as f:
            f.write("CORRUPTED")

        new_dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch(custom_data_dir=self.data_folder) # This should load the corrupted file, reset it to [], and add the new_dna

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Since VOL08900750712 was in the ledger, it was NOT re-processed.
        # Only VOL00000000000 is in the new output.
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], new_dna)

if __name__ == '__main__':
    unittest.main()

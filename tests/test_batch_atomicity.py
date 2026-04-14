import os
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestBatchAtomicity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Create a dummy rules directory
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.rules_dir)
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "Amplitude", "min": 0, "max": 9999, "pad": 4}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_atomicity_on_failure(self):
        """
        Verify that if an error occurs during the commit phase,
        none of the output files are updated.
        """
        dna = "VOL0890"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # First, ensure files don't exist
        self.assertFalse(os.path.exists(self.ledger_path))
        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))

        # Mock os.replace to fail when trying to move the json output
        with patch('os.replace', side_effect=OSError("Simulated IO failure")):
            with self.assertRaises(PersistenceError):
                run_batch(data_dir=self.test_dir)

        # Verify that NO files were created/moved to their final location
        self.assertFalse(os.path.exists(self.ledger_path), "Ledger should NOT exist after failed commit")
        self.assertFalse(os.path.exists(self.json_output), "JSON output should NOT exist after failed commit")
        self.assertFalse(os.path.exists(self.csv_output), "CSV output should NOT exist after failed commit")

    def test_successful_atomic_commit(self):
        """
        Verify that all files are created correctly on success.
        """
        dna = "VOL0890"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(data_dir=self.test_dir)

        self.assertTrue(os.path.exists(self.ledger_path))
        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

if __name__ == '__main__':
    unittest.main()

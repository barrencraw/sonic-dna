import os
import json
import shutil
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestBatchAtomicity(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Clean slate
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initial state: Ledger and JSON output have some content
        self.initial_dna = "VOL08900750712"
        with open(self.ledger_path, 'w') as f:
            json.dump({self.initial_dna: {"terminal_outcome": "success", "timestamp": "2025-01-01 00:00:00"}}, f)

        with open(self.json_output, 'w') as f:
            json.dump([{"dna": self.initial_dna, "rule": "Volume", "parsed": {"amp": 890, "pan": 750, "v_curve": 712}}], f)

    def test_failure_during_atomic_commit_leaves_files_unchanged(self):
        """
        Verify that if os.replace fails (simulated via mock), none of the files are updated.
        """
        new_dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        # Mock os.replace to raise an exception when trying to commit the JSON file
        with patch('os.replace', side_effect=OSError("Atomic commit failed")):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Verify files are UNCHANGED
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(list(ledger.keys()), [self.initial_dna], "Ledger should NOT have been updated")

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "JSON output should NOT have been updated")
        self.assertEqual(data[0]['dna'], self.initial_dna)

if __name__ == '__main__':
    unittest.main()

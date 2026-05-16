import os
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestAtomicity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_folder = os.path.join(self.test_dir, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Symlink rules folder to the test dir
        os.symlink(os.path.join(os.getcwd(), 'rules'), os.path.join(self.test_dir, 'rules'))

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_failure_during_write_prevents_ledger_update(self):
        # DNA to process
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Mock json.dump to fail
        with patch('json.dump', side_effect=IOError("Disk Full")):
            with self.assertRaises(PersistenceError):
                run_batch(project_root=self.test_dir)

        # Verify ledger was NOT updated on disk
        self.assertFalse(os.path.exists(self.ledger_path))

        # Verify output was NOT created
        json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_output))

    def test_partial_rename_failure_behavior(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Mock os.replace to fail on the second call (CSV rename)
        original_replace = os.replace
        call_count = 0
        def side_effect(src, dst):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("Permission Denied")
            return original_replace(src, dst)

        with patch('os.replace', side_effect=side_effect):
            with self.assertRaises(PersistenceError):
                run_batch(project_root=self.test_dir)

if __name__ == '__main__':
    unittest.main()

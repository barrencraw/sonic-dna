import os
import json
import csv
import unittest
import subprocess
import shutil
from utils.dna_ui import main as run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data_maintainability')
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(os.path.join(self.data_folder, 'raw'), exist_ok=True)
        os.makedirs(os.path.join(self.data_folder, 'output'), exist_ok=True)
        # Copy rules to maintainability folder
        shutil.copytree(os.path.join(self.project_root, 'rules'), os.path.join(self.data_folder, 'rules'))

        # Patch dna_ui paths to use maintainability folder
        import utils.dna_ui
        self.orig_os_getcwd = os.getcwd
        os.getcwd = lambda: self.data_folder

    def tearDown(self):
        os.getcwd = self.orig_os_getcwd
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)

    def test_naming_and_status_alignment(self):
        dna = "VOL08900750712"
        input_file = os.path.join(self.data_folder, 'data', 'raw', 'toSequence.txt')
        os.makedirs(os.path.dirname(input_file), exist_ok=True)
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-cid")

        # 1. Verify JSON key naming
        json_out = os.path.join(self.data_folder, 'data', 'output', 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
        self.assertIn('dna_sequence', data[0], "JSON output should use 'dna_sequence' key")
        self.assertNotIn('dna', data[0], "JSON output should NOT use legacy 'dna' key")

        # 2. Verify Ledger status values
        ledger_path = os.path.join(self.data_folder, 'data', 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna]['terminal_outcome'], DNAStatus.SUCCESS.value, "Ledger should use DNAStatus values")

    def test_structured_logging_format(self):
        dna = "VOL08900750712"
        # We'll run via subprocess to capture stdout easily
        raw_dir = os.path.join(self.project_root, 'data', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        input_file = os.path.join(raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        # Ensure ledger is clean
        ledger_file = os.path.join(self.project_root, 'data', 'processed_ledger.json')
        if os.path.exists(ledger_file):
            os.remove(ledger_file)

        result = subprocess.run(['python3', 'main.py', '--once'], capture_output=True, text=True)

        found_log = False
        for line in result.stdout.splitlines():
            if line.startswith("JSON_LOG:"):
                found_log = True
                log_data = json.loads(line.replace("JSON_LOG: ", ""))
                required_keys = ["timestamp", "correlation_id", "chain_name", "step", "outcome", "actor_id"]
                for key in required_keys:
                    self.assertIn(key, log_data)
                self.assertEqual(log_data["chain_name"], "dna_batch")

        self.assertTrue(found_log, "Should have found at least one structured log entry")

if __name__ == '__main__':
    unittest.main()

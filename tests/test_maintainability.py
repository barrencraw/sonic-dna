import os
import json
import unittest
import shutil
import io
import sys
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Backup and clear
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maintain')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_json_log_format_and_naming_alignment(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cid-123")

        output = f.getvalue()

        # 1. Verify JSON_LOG prefix and structure
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]
        self.assertTrue(len(log_lines) > 0, "No JSON_LOG entries found")

        for line in log_lines:
            log_json_str = line.replace("JSON_LOG: ", "")
            log_data = json.loads(log_json_str)
            self.assertEqual(log_data["correlation_id"], "test-cid-123")
            self.assertIn("timestamp", log_data)
            self.assertIn("step", log_data)
            self.assertIn("outcome", log_data)
            self.assertEqual(log_data["chain_name"], "dna_batch_processing")

        # 2. Verify dna_sequence naming in output JSON
        json_output_path = os.path.join(self.output_folder, 'toSequence_parsed.json')
        with open(json_output_path, 'r') as jf:
            parsed_data = json.load(jf)

        self.assertTrue(len(parsed_data) > 0)
        self.assertIn("dna_sequence", parsed_data[0])
        self.assertNotIn("dna", parsed_data[0])
        self.assertEqual(parsed_data[0]["dna_sequence"], dna)

if __name__ == '__main__':
    unittest.main()

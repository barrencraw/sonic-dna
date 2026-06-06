import os
import json
import shutil
import unittest
import io
import contextlib
from utils.dna_ui import main as run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maint')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_naming_and_logging_standards(self):
        dna_sequence = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_sequence + "\n")

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch(correlation_id="test-id")

        output = f.getvalue()

        # 1. Verify structured logs
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]
        self.assertGreater(len(log_lines), 0, "Should have produced at least one structured log")

        found_parse_complete = False
        for line in log_lines:
            log_data = json.loads(line.split("JSON_LOG:")[1])
            self.assertEqual(log_data["correlation_id"], "test-id")
            self.assertIn("timestamp", log_data)
            self.assertIn("chain_name", log_data)
            self.assertIn("step", log_data)
            self.assertIn("outcome", log_data)
            if log_data["step"] == "parse" and log_data["outcome"] == DNAStatus.SUCCESS.value:
                found_parse_complete = True
                self.assertEqual(log_data["idempotency_key"], dna_sequence)

        self.assertTrue(found_parse_complete, "Should have found a successful parse log step")

        # 2. Verify naming in output JSON
        with open(self.json_output, 'r') as jf:
            data = json.load(jf)
            self.assertEqual(data[0]['dna_sequence'], dna_sequence, "JSON output should use 'dna_sequence' key")

if __name__ == '__main__':
    unittest.main()

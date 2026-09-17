import os
import json
import shutil
import unittest
import io
import sys
from unittest.mock import patch
from utils.dna_ui import run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup_maint')
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

    def test_dnastatus_enum_properties(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_backward_compatibility_output_keys(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-maint-keys")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn('dna', data[0], "Output entry must contain legacy key 'dna'")
        self.assertIn('dna_sequence', data[0], "Output entry must contain canonical key 'dna_sequence'")
        self.assertEqual(data[0]['dna'], dna)
        self.assertEqual(data[0]['dna_sequence'], dna)

    def test_structured_logging_format(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        stdout_capture = io.StringIO()
        with patch.object(sys, 'stdout', stdout_capture):
            run_batch(correlation_id="test-structured-logs")

        log_output = stdout_capture.getvalue()
        json_log_lines = [line for line in log_output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(json_log_lines), 0, "Should emit JSON_LOG entries")

        for line in json_log_lines:
            json_str = line.replace("JSON_LOG:", "").strip()
            log_data = json.loads(json_str)
            required_keys = ["timestamp", "correlation_id", "actor_id", "chain_name", "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"]
            for key in required_keys:
                self.assertIn(key, log_data, f"Structured log missing key '{key}'")
            self.assertEqual(log_data["correlation_id"], "test-structured-logs")

if __name__ == '__main__':
    unittest.main()

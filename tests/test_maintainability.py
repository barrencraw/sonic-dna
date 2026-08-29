import os
import json
import io
import sys
import shutil
import unittest
from utils.dna_ui import run_batch, DNAStatus, log_structured


class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_dnastatus_lowercase_properties(self):
        self.assertEqual(DNAStatus.SUCCESS, 'success')
        self.assertEqual(DNAStatus.ERROR, 'error')
        self.assertEqual(DNAStatus.SKIPPED, 'skipped')
        self.assertEqual(DNAStatus.REFUSED, 'refused')

    def test_structured_logging_format(self):
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            log_structured("cid-123", "actor-test", "chain-test", "step-test", "success")
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = ["timestamp", "correlation_id", "actor_id", "chain_name", "step", "outcome", "latency_ms"]
        for k in required_keys:
            self.assertIn(k, log_data)
        self.assertEqual(log_data["correlation_id"], "cid-123")
        self.assertEqual(log_data["actor_id"], "actor-test")

    def test_backward_compatibility_keys(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertIn('dna', data[0])
        self.assertIn('dna_sequence', data[0])
        self.assertEqual(data[0]['dna'], dna)
        self.assertEqual(data[0]['dna_sequence'], dna)


if __name__ == '__main__':
    unittest.main()

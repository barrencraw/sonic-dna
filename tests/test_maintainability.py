import os
import json
import io
import shutil
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, DNAStatus, log_structured, UI_MESSAGES

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

        if os.path.exists(self.data_folder):
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

    def test_dna_status_lowercase_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_schema(self):
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            log_structured("test_corr_123", "test_actor", "test_chain", "parse_step", DNAStatus.SUCCESS.value, 15, "KEY123", "success_detail")

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output.replace("JSON_LOG: ", "")
        data = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, data)

        self.assertEqual(data["correlation_id"], "test_corr_123")
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["chain_name"], "test_chain")
        self.assertEqual(data["step"], "parse_step")
        self.assertEqual(data["outcome"], "success")

    def test_backwards_compatible_outputs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            parsed = json.load(f)

        self.assertEqual(len(parsed), 1)
        entry = parsed[0]
        self.assertIn('dna', entry)
        self.assertIn('dna_sequence', entry)
        self.assertEqual(entry['dna'], dna)
        self.assertEqual(entry['dna_sequence'], dna)

if __name__ == '__main__':
    unittest.main()

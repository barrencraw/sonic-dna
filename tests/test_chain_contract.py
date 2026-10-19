import sys
from unittest.mock import MagicMock

# Mock dependencies before imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import os
import io
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import run_batch, PersistenceError

class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        # Copy existing rules into temporary rules directory
        proj_rules = os.path.join(os.getcwd(), 'rules')
        if os.path.exists(proj_rules):
            for fname in os.listdir(proj_rules):
                fpath = os.path.join(proj_rules, fname)
                if os.path.isfile(fpath):
                    shutil.copy(fpath, os.path.join(self.rules_dir, fname))

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_batch_parsing(self):
        valid_dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(valid_dna + "\n")

        run_batch(correlation_id="test-corr-123")

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], valid_dna)

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn(valid_dna, ledger)
            self.assertEqual(ledger[valid_dna]['terminal_outcome'], 'success')

    def test_idempotency_double_invocation(self):
        valid_dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(valid_dna + "\n")

        # First run
        run_batch(correlation_id="test-corr-1")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data_first = json.load(f)
        self.assertEqual(len(data_first), 1)

        # Second run with same input
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(valid_dna + "\n")

        run_batch(correlation_id="test-corr-2")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data_second = json.load(f)
        # Deduplication hit -> output should still have only 1 entry
        self.assertEqual(len(data_second), 1)

    def test_persistence_failure_adversarial(self):
        valid_dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(valid_dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-fail-1")

        self.assertFalse(os.path.exists(self.json_output))
        self.assertFalse(os.path.exists(self.csv_output))

    def test_telemetry_log_emission(self):
        valid_dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(valid_dna + "\n")

        stdout_capture = io.StringIO()
        with patch('sys.stdout', stdout_capture):
            run_batch(correlation_id="test-telemetry-999")

        output = stdout_capture.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(log_lines), 0)

        for line in log_lines:
            json_str = line.replace("JSON_LOG:", "")
            log_data = json.loads(json_str)
            self.assertEqual(log_data['correlation_id'], "test-telemetry-999")
            self.assertEqual(log_data['chain_name'], "dna_batch_parse")
            self.assertEqual(log_data['actor_id'], "batch_parser")
            self.assertIn('timestamp', log_data)
            self.assertIn('step', log_data)
            self.assertIn('outcome', log_data)
            self.assertIn('latency_ms', log_data)
            self.assertIn('idempotency_key', log_data)
            self.assertIn('outcome_detail', log_data)

if __name__ == '__main__':
    unittest.main()

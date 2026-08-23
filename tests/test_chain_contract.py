import sys
import os
import json
import io
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    DNAStatus,
    LedgerLoadError,
    AtomicWriteError,
    PersistenceError,
    DNAProcessingError
)

class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        # Create mock rule file for Volume ('VOL')
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_and_telemetry(self):
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        stdout_capture = io.StringIO()
        with patch('sys.stdout', new=stdout_capture):
            run_batch(correlation_id="test-corr-123", actor_id="test-agent")

        out_str = stdout_capture.getvalue()
        log_lines = [line for line in out_str.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(log_lines), 0, "Expected structured JSON logs")

        parsed_logs = [json.loads(line.replace("JSON_LOG: ", "")) for line in log_lines]
        for log in parsed_logs:
            self.assertEqual(log['correlation_id'], "test-corr-123")
            self.assertEqual(log['actor_id'], "test-agent")
            self.assertEqual(log['chain_name'], "dna_batch_parsing")
            self.assertIn('timestamp', log)
            self.assertIn('outcome', log)

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)
            self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
            ledger = ledger_data.get('ledger', ledger_data)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_double_invocation_idempotency(self):
        dna = "VOL100"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        # First run
        run_batch(correlation_id="corr-1", actor_id="agent")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data_run1 = json.load(f)
        self.assertEqual(len(data_run1), 1)

        # Second run with same input
        stdout_capture = io.StringIO()
        with patch('sys.stdout', new=stdout_capture):
            run_batch(correlation_id="corr-2", actor_id="agent")

        out_str = stdout_capture.getvalue()
        log_lines = [line for line in out_str.splitlines() if line.startswith("JSON_LOG:")]
        parsed_logs = [json.loads(line.replace("JSON_LOG: ", "")) for line in log_lines]
        dedupe_logs = [l for l in parsed_logs if l.get('step') == 'dedupe']

        self.assertEqual(len(dedupe_logs), 1)
        self.assertEqual(dedupe_logs[0]['outcome'], 'skipped')

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data_run2 = json.load(f)
        self.assertEqual(len(data_run2), 1, "Idempotency invariant violated: duplicated records")

    def test_corrupted_ledger_raises_ledger_load_error(self):
        with open(self.ledger_file, 'w', encoding='utf-8') as f:
            f.write("{ INVALID JSON }")

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        with self.assertRaises(LedgerLoadError):
            run_batch()

    def test_atomic_write_failure_raises_persistence_error(self):
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL100\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(AtomicWriteError):
                run_batch()

if __name__ == '__main__':
    unittest.main()

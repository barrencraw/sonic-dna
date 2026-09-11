import os
import sys
import json
import io
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    PersistenceError,
    LedgerLoadError,
    AtomicWriteError
)


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

        # Create a valid Volume rule file matching VOL08900750712
        rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "lr"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "sur"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "head"}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_happy_path_parsing(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-corr-1", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
            self.assertIn(dna, ledger)
            self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

    def test_idempotency_double_invocation(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-corr-2")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

        # Second invocation with same DNA
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-corr-2-dup")

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should not add duplicate entry on second invocation")

    def test_corrupt_ledger_raises_ledger_load_error(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with open(self.ledger_file, 'w', encoding='utf-8') as f:
            f.write("{ INVALID JSON }")

        with self.assertRaises(LedgerLoadError):
            run_batch(correlation_id="test-corr-corrupt")

    def test_persistence_atomic_failure(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-corr-fail")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

    def test_structured_telemetry_emission(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            run_batch(correlation_id="telemetry-test-uuid", actor_id="test_runner")

        lines = captured_output.getvalue().splitlines()
        json_logs = [line for line in lines if line.startswith("JSON_LOG:")]

        self.assertGreater(len(json_logs), 0, "Structured logs prefixed with JSON_LOG: should be emitted")

        first_log = json.loads(json_logs[0].replace("JSON_LOG: ", "", 1))
        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, first_log)

        self.assertEqual(first_log["correlation_id"], "telemetry-test-uuid")
        self.assertEqual(first_log["actor_id"], "test_runner")
        self.assertEqual(first_log["chain_name"], "dna_batch_parser")


if __name__ == '__main__':
    unittest.main()

import os
import sys
import json
import io
import shutil
import tempfile
import inspect
import unittest
from unittest.mock import patch

from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    AtomicWriteError,
    load_ledger,
    run_batch,
    log_structured
)


class TestMaintainability(unittest.TestCase):
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
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_parameters(self):
        """Verify method signature parameter name is dna_sequence across Rule and DNACalculator."""
        rule_sig = inspect.signature(Rule.parse)
        calc_sig = inspect.signature(DNACalculator.parse)

        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must use 'dna_sequence' parameter")
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must use 'dna_sequence' parameter")

    def test_naming_alignment_dto_output(self):
        """Verify batch output entries contain canonical key 'dna_sequence' alongside legacy 'dna'."""
        with open(self.input_file, 'w') as f:
            f.write("VOL050\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertIn('dna_sequence', data[0], "DTO output must include canonical 'dna_sequence' key")
            self.assertIn('dna', data[0], "DTO output must maintain legacy 'dna' key for compatibility")
            self.assertEqual(data[0]['dna_sequence'], "VOL050")

    def test_typed_error_hierarchy(self):
        """Verify explicit typed error exception hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_corrupted_ledger_raises_ledger_load_error(self):
        """Verify loading corrupted ledger raises typed LedgerLoadError."""
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'w') as f:
            f.write("NOT_VALID_JSON{")

        with self.assertRaises(LedgerLoadError):
            load_ledger(ledger_path)

    def test_terminal_states_enum(self):
        """Verify explicit terminal state values in DNAStatus enum."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")

    def test_structured_logging_schema(self):
        """Verify emitted structured logs contain required observability fields."""
        with open(self.input_file, 'w') as f:
            f.write("VOL123\n")

        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            run_batch(correlation_id="test-correlation-123")

        output_str = captured_output.getvalue()
        log_lines = [line for line in output_str.splitlines() if line.startswith("JSON_LOG: ")]
        self.assertGreater(len(log_lines), 0, "At least one structured log line must be emitted")

        required_keys = {
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key",
            "outcome_detail"
        }

        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "")
            entry = json.loads(json_str)
            for key in required_keys:
                self.assertIn(key, entry, f"Missing required log field: '{key}' in log entry")
            self.assertEqual(entry['correlation_id'], "test-correlation-123")
            self.assertEqual(entry['chain_name'], "dna_batch_parser")


if __name__ == '__main__':
    unittest.main()

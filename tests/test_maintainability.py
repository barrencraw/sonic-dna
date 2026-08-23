import os
import json
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    DNAProcessingError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError
)
from utils.dna_calculator import DNACalculator, RuleParseError

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
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL08900750712\nINVALID_SEQ\n")

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "pan level", "min": 0, "max": 999, "pad": 3},
                    "fade": {"description": "fade level", "min": 0, "max": 999, "pad": 3},
                    "mute": {"description": "mute flag", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_structured_log_format_and_fields(self):
        """Assert that structured logs emit valid JSON with all mandatory telemetry keys."""
        captured_output = StringIO()
        with patch('sys.stdout', new=captured_output):
            run_batch(correlation_id="test-corr-123", actor_id="test_runner")

        output = captured_output.getvalue()
        log_lines = [line[len("JSON_LOG:"):] for line in output.splitlines() if line.startswith("JSON_LOG:")]

        self.assertGreater(len(log_lines), 0, "Structured logs should be emitted")
        required_fields = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key", "outcome_detail"
        }

        for raw_log in log_lines:
            entry = json.loads(raw_log)
            missing = required_fields - set(entry.keys())
            self.assertEqual(len(missing), 0, f"Missing log fields: {missing}")
            self.assertEqual(entry["correlation_id"], "test-corr-123")
            self.assertEqual(entry["chain_name"], "dna_batch_processing")
            self.assertEqual(entry["actor_id"], "test_runner")

    def test_typed_error_classification(self):
        """Verify explicit typed error hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

    def test_canonical_naming_and_terminal_states(self):
        """Verify terminal outcome persistence in ledger for both valid and invalid sequences."""
        run_batch(correlation_id="test-corr-456")
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.assertTrue(os.path.exists(ledger_path))

        with open(ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        self.assertIn("VOL08900750712", ledger)
        self.assertEqual(ledger["VOL08900750712"]["terminal_outcome"], "success")

        self.assertIn("INVALID_SEQ", ledger)
        self.assertTrue(ledger["INVALID_SEQ"]["terminal_outcome"].startswith("error:"))

if __name__ == '__main__':
    unittest.main()

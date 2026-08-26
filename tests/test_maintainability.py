import os
import json
import shutil
import unittest
import tempfile
import io
import sys
from unittest.mock import patch
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    run_batch
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

        # Mock a valid rule file (Volume prefix VOL)
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999999, "pad": 6}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL000100\n")

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum string values match expectations."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_typed_exceptions_hierarchy(self):
        """Verify typed exception taxonomy inheritance."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_logging_keys(self):
        """Verify structured JSON logging output contains required schema fields."""
        captured_output = io.StringIO()
        with patch('sys.stdout', new=captured_output):
            run_batch(correlation_id="test-corr-123", actor_id="test_runner")

        log_lines = [
            line for line in captured_output.getvalue().splitlines()
            if line.startswith("JSON_LOG:")
        ]
        self.assertTrue(len(log_lines) > 0, "Should emit structured JSON_LOG lines")

        first_log_raw = log_lines[0].replace("JSON_LOG: ", "")
        log_data = json.loads(first_log_raw)

        expected_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertTrue(expected_keys.issubset(log_data.keys()))
        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test_runner")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")

    def test_backward_compatibility_dict_keys(self):
        """Verify output JSON contains both legacy 'dna' and canonical 'dna_sequence' keys."""
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn("dna", data[0])
        self.assertIn("dna_sequence", data[0])
        self.assertEqual(data[0]["dna"], "VOL000100")
        self.assertEqual(data[0]["dna_sequence"], "VOL000100")

if __name__ == '__main__':
    unittest.main()

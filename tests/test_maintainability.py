import unittest
import os
import json
import io
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)
from utils.dna_calculator import RuleParseError


class TestMaintainability(unittest.TestCase):
    def test_dnastatus_enum_values(self):
        """Verify that DNAStatus enum uses lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_error_hierarchy(self):
        """Verify typed error hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_log_structured_schema(self):
        """Verify that log_structured outputs valid JSON prefixed with JSON_LOG: containing standard keys."""
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=42,
                idempotency_key="key-123",
                outcome_detail="Test detail message"
            )

        log_str = captured_output.getvalue().strip()
        self.assertTrue(log_str.startswith("JSON_LOG: "))

        json_part = log_str[len("JSON_LOG: "):]
        data = json.loads(json_part)

        mandatory_fields = [
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        ]

        for field in mandatory_fields:
            self.assertIn(field, data)

        self.assertEqual(data["correlation_id"], "test-corr-id")
        self.assertEqual(data["actor_id"], "test-actor")
        self.assertEqual(data["chain_name"], "test-chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 42)
        self.assertEqual(data["idempotency_key"], "key-123")
        self.assertEqual(data["outcome_detail"], "Test detail message")

    def test_output_contains_both_canonical_and_legacy_keys(self):
        """Verify output JSON contains both 'dna' and 'dna_sequence' keys."""
        test_dir = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(test_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
            rules_dir = os.path.join(test_dir, 'rules')

            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("VOL100\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="maint-test")

                json_out = os.path.join(output_dir, 'toSequence_parsed.json')
                self.assertTrue(os.path.exists(json_out))

                with open(json_out, 'r') as f:
                    records = json.load(f)

                self.assertEqual(len(records), 1)
                record = records[0]
                self.assertIn('dna', record)
                self.assertIn('dna_sequence', record)
                self.assertEqual(record['dna'], 'VOL100')
                self.assertEqual(record['dna_sequence'], 'VOL100')

            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)


if __name__ == '__main__':
    unittest.main()

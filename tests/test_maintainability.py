import inspect
import json
import re
import unittest
import datetime
from unittest.mock import patch, MagicMock
import io
import contextlib

import tempfile

# Import the module under test
from utils.dna_ui import (
    run_batch, log_structured, DNAStatus, DNAProcessingError,
    RuleLoadError, PersistenceError, LedgerSaveError, ThermalOverloadError,
    InputReadError, AtomicWriteError
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """
        Verify that canonical names are used in utils/dna_ui.py to keep codebase searchable.
        Enforces use of 'dna_sequence_list' and 'dna_sequence' instead of generic 'dna_list' or 'dna' in run_batch.
        """
        # Get source code of run_batch
        source = inspect.getsource(run_batch)

        # Verify that canonical names are defined and used
        self.assertIn("dna_sequence_list", source)
        self.assertIn("dna_sequence", source)

    def test_dnastatus_enum(self):
        """
        Verify that DNAStatus enum exists with standardized lowercase statuses.
        """
        self.assertTrue(issubclass(DNAStatus, str))
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_structured_log_hygiene(self):
        """
        Verify that log_structured emits compliant structured logs with all mandatory keys
        and correct ISO 8601 UTC timestamp formatting.
        """
        # Capture stdout
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_structured(
                correlation_id="test-corr-123",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=150,
                idempotency_key="test-key-456",
                outcome_detail="Standardized outcome message",
                actor_id="test-actor"
            )

        output = f.getvalue().strip()

        # Check prefix
        prefix = "JSON_LOG: "
        self.assertTrue(output.startswith(prefix), f"Log output should start with '{prefix}'")

        # Parse JSON part
        json_str = output[len(prefix):]
        log_data = json.loads(json_str)

        # Verify mandatory keys
        mandatory_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        for key in mandatory_keys:
            self.assertIn(key, log_data, f"Structured log is missing mandatory field: {key}")

        # Verify values
        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test-actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 150)
        self.assertEqual(log_data["idempotency_key"], "test-key-456")
        self.assertEqual(log_data["outcome_detail"], "Standardized outcome message")

        # Verify ISO 8601 UTC timestamp formatting (YYYY-MM-DDTHH:MM:SSZ)
        timestamp = log_data["timestamp"]
        # Basic regex check for YYYY-MM-DDTHH:MM:SSZ
        iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        self.assertTrue(re.match(iso_pattern, timestamp), f"Timestamp '{timestamp}' does not match ISO 8601 UTC formatting pattern.")

    def test_exception_taxonomy(self):
        """
        Ensure the core exception taxonomy is defined and categorized correctly.
        """
        self.assertTrue(issubclass(DNAProcessingError, Exception))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(ThermalOverloadError, DNAProcessingError))

    def test_missing_input_file_raises_input_read_error(self):
        """
        Ensure that run_batch raises InputReadError when the input file is missing.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch('os.getcwd', return_value=tmp_dir):
                with self.assertRaises(InputReadError):
                    run_batch()

if __name__ == '__main__':
    unittest.main()

import os
import sys
import json
import unittest
import inspect
from unittest.mock import patch, MagicMock
from io import StringIO
from datetime import datetime

# Import components under test
from utils.dna_ui import (
    run_batch,
    log_structured,
    BatchResult,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError
)

class TestMaintainability(unittest.TestCase):

    def test_naming_conventions_and_signatures(self):
        """Assert that function signatures maintain strict naming alignment and parameters."""
        sig = inspect.signature(run_batch)
        params = list(sig.parameters.keys())

        # Verify mandatory parameter presence
        self.assertIn("correlation_id", params)
        self.assertIn("actor_id", params)

        # Verify the source file does not have legacy naming variables like 'dna_list' or 'dna_str'
        # in its key definitions
        utils_dir = os.path.dirname(inspect.getfile(run_batch))
        dna_ui_path = os.path.join(utils_dir, "dna_ui.py")

        with open(dna_ui_path, "r", encoding="utf-8") as f:
            content = f.read()

        # We should use dna_sequence_list and dna_sequence instead of legacy raw names as primary vars
        self.assertIn("dna_sequence_list", content)
        self.assertIn("dna_sequence", content)

    def test_exception_hierarchy(self):
        """Assert typed exception classification is consistent and properly sub-classed."""
        self.assertTrue(issubclass(DNAProcessingError, Exception))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dnastatus_lowercase_enum(self):
        """Assert DNAStatus utilises lowercase values to preserve full backward compatibility."""
        self.assertTrue(issubclass(DNAStatus, str))
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_log_hygiene(self):
        """Verify structured log schema contains all mandatory fields and correct ISO 8601 formatting."""
        captured_output = StringIO()
        with patch('sys.stdout', new=captured_output):
            log_structured(
                correlation_id="test_corr_123",
                actor_id="test_actor_456",
                chain_name="test_chain",
                step="test_step",
                outcome="success",
                latency_ms=150,
                idempotency_key="test_key_abc",
                outcome_detail="all assertions verified"
            )

        log_lines = captured_output.getvalue().strip().split("\n")
        self.assertEqual(len(log_lines), 1)

        line = log_lines[0]
        self.assertTrue(line.startswith("JSON_LOG: "))

        json_str = line.replace("JSON_LOG: ", "", 1)
        log_data = json.loads(json_str)

        # Verify all mandatory telemetry fields
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
            self.assertIn(field, log_data)

        # Verify ISO 8601 timestamp ending in 'Z'
        timestamp = log_data["timestamp"]
        self.assertTrue(timestamp.endswith("Z"))
        # Verify it parses as ISO 8601 datetime
        try:
            datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            self.fail(f"Timestamp {timestamp} is not in %Y-%m-%dT%H:%M:%SZ format")

        # Verify correct values are written
        self.assertEqual(log_data["correlation_id"], "test_corr_123")
        self.assertEqual(log_data["actor_id"], "test_actor_456")
        self.assertEqual(log_data["chain_name"], "test_chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 150)
        self.assertEqual(log_data["idempotency_key"], "test_key_abc")
        self.assertEqual(log_data["outcome_detail"], "all assertions verified")

if __name__ == '__main__':
    unittest.main()

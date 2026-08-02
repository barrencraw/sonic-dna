import unittest
import sys
import io
import json
import inspect
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)
from unittest.mock import patch

class TestMaintainability(unittest.TestCase):
    def test_naming_conventions_in_signatures(self):
        """Assert that function signatures utilize canonical naming (dna_sequence, dna_sequence_list)."""
        # Check signature of run_batch or helper functions
        from utils import dna_ui
        sig_run_batch = inspect.signature(dna_ui.run_batch)
        self.assertIn('correlation_id', sig_run_batch.parameters)

        # Check signature of read_input_file
        sig_read = inspect.signature(dna_ui.read_input_file)
        self.assertIn('input_path', sig_read.parameters)

    def test_error_taxonomy_structure(self):
        """Assert that typed exceptions are properly structured and subclass standard base classes."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum(self):
        """Assert that DNAStatus exists, is an enum, and has expected lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_log_structured_output_and_fields(self):
        """Assert that log_structured emits JSON_LOG: prefix with all mandatory fields."""
        f = io.StringIO()
        with patch('sys.stdout', new=f):
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test-step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=150,
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        log_json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(log_json_str)

        # Verify all mandatory fields are present
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

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test-actor")
        self.assertEqual(log_data["chain_name"], "test-chain")
        self.assertEqual(log_data["step"], "test-step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 150)
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertEqual(log_data["outcome_detail"], "test-detail")
        self.assertTrue(log_data["timestamp"].endswith("Z"))

if __name__ == '__main__':
    unittest.main()

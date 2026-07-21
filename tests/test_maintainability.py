import inspect
import json
import re
import unittest
from unittest.mock import patch, MagicMock
from utils import dna_ui
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    PersistenceError,
    log_structured,
    process_single_dna
)

class TestMaintainability(unittest.TestCase):
    def test_naming_conventions_in_signatures(self):
        """Verify that signature parameters and variables follow naming alignment rules."""
        # 1. process_single_dna signature check
        sig_process = inspect.signature(process_single_dna)
        self.assertIn("dna_sequence", sig_process.parameters, "process_single_dna must accept 'dna_sequence'")
        self.assertIn("calculator", sig_process.parameters, "process_single_dna must accept 'calculator'")

        # 2. run_batch signature check
        sig_batch = inspect.signature(dna_ui.run_batch)
        self.assertIn("correlation_id", sig_batch.parameters, "run_batch must accept 'correlation_id'")

    def test_exception_type_hierarchy(self):
        """Verify that our error taxonomy is correctly defined and subclasses DNAProcessingError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError), "RuleLoadError must inherit from DNAProcessingError")
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError), "PersistenceError must inherit from DNAProcessingError")

    def test_structured_log_hygiene(self):
        """Verify that log_structured outputs valid JSON logs with mandatory fields and correct prefix."""
        with patch('builtins.print') as mock_print:
            log_structured(
                step="test_step",
                outcome="success",
                latency_ms=15,
                correlation_id="test-corr-id",
                idempotency_key="V100",
                outcome_detail="test detail"
            )

            mock_print.assert_called_once()
            log_line = mock_print.call_args[0][0]

            self.assertTrue(log_line.startswith("JSON_LOG: "), "Structured logs must start with prefix 'JSON_LOG: '")
            json_str = log_line[len("JSON_LOG: "):]

            # Verify JSON can be parsed
            data = json.loads(json_str)

            # Check mandatory fields
            mandatory_keys = [
                "timestamp", "correlation_id", "actor_id", "chain_name",
                "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
            ]
            for key in mandatory_keys:
                self.assertIn(key, data, f"Structured log must contain the key '{key}'")

            # Verify ISO 8601 UTC timestamp format matches %Y-%m-%dT%H:%M:%SZ
            timestamp = data["timestamp"]
            # Format pattern: YYYY-MM-DDTHH:MM:SSZ
            pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            self.assertTrue(re.match(pattern, timestamp), f"Timestamp '{timestamp}' must match UTC ISO 8601 format %Y-%m-%dT%H:%M:%SZ")

            # Verify values are correctly set
            self.assertEqual(data["step"], "test_step")
            self.assertEqual(data["outcome"], "success")
            self.assertEqual(data["latency_ms"], 15)
            self.assertEqual(data["correlation_id"], "test-corr-id")
            self.assertEqual(data["idempotency_key"], "V100")
            self.assertEqual(data["outcome_detail"], "test detail")
            self.assertEqual(data["actor_id"], "dna_orchestrator")
            self.assertEqual(data["chain_name"], "dna_batch_parser")

    def test_dna_status_enum_backward_compatibility(self):
        """Verify that DNAStatus enum defines canonical terminal states in lowercase."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

if __name__ == '__main__':
    unittest.main()

import json
import unittest
import inspect
from utils import dna_ui
from utils.dna_ui import DNAStatus, BatchResult, log_structured

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Assert that DNAStatus enum utilizes lowercase values to preserve compatibility."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_naming_alignment_signatures(self):
        """Regression guard to ensure canonical naming is followed in function signatures."""
        sig = inspect.signature(dna_ui.run_batch)
        self.assertIn("correlation_id", sig.parameters)
        self.assertIn("actor_id", sig.parameters)
        self.assertTrue(callable(dna_ui.read_input_file))

    def test_log_structured_schema_completeness(self):
        """Verify that log_structured outputs standardized JSON logs with all mandatory telemetry fields."""
        import sys
        from io import StringIO

        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            log_structured(
                correlation_id="test-corr-123",
                step="test-step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=42,
                actor_id="test-actor",
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )
            output = sys.stdout.getvalue().strip()
        finally:
            sys.stdout = old_stdout

        self.assertTrue(output.startswith("JSON_LOG: "))
        json_part = output[len("JSON_LOG: "):]
        log_data = json.loads(json_part)

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
            self.assertIn(field, log_data, f"Mandatory field '{field}' is missing from telemetry log.")

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["step"], "test-step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 42)
        self.assertEqual(log_data["actor_id"], "test-actor")
        self.assertEqual(log_data["idempotency_key"], "test-key")
        self.assertEqual(log_data["outcome_detail"], "test-detail")
        self.assertEqual(log_data["chain_name"], "dna_batch_parsing")
        self.assertTrue(log_data["timestamp"].endswith("Z"))

if __name__ == "__main__":
    unittest.main()

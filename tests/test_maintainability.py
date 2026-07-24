import unittest
import inspect
import io
import sys
import json
import re
from utils.dna_ui import run_batch, log_structured, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_alignment(self):
        """Verify that signature parameters use correlation_id."""
        sig = inspect.signature(run_batch)
        self.assertIn("correlation_id", sig.parameters, "run_batch must accept correlation_id parameter.")

    def test_dna_status_enum_values(self):
        """Verify that DNAStatus contains lowercase terminal outcome values."""
        expected_statuses = {"success", "error", "skipped", "refused"}
        for status in DNAStatus:
            self.assertIn(status.value, expected_statuses, f"Status value {status.value} must be one of {expected_statuses}.")
            self.assertEqual(status.value, status.value.lower(), f"Status value {status.value} must be lowercase.")

    def test_structured_log_hygiene(self):
        """Verify that log_structured prints JSON logs with the correct prefix, keys, and timestamp format."""
        old_stdout = sys.stdout
        captured = io.StringIO()
        sys.stdout = captured
        try:
            log_structured(
                correlation_id="test-correlation-123",
                step="test-step-validate",
                outcome=DNAStatus.SUCCESS,
                latency_ms=45,
                idempotency_key="V100_TEST",
                outcome_detail="Validation completed successfully"
            )
        finally:
            sys.stdout = old_stdout

        log_output = captured.getvalue().strip()
        self.assertTrue(log_output.startswith("JSON_LOG:"), "Structured log must start with 'JSON_LOG:' prefix.")

        json_str = log_output.replace("JSON_LOG:", "").strip()
        try:
            log_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            self.fail(f"Failed to parse structured log JSON payload: {e}")

        # Assert mandatory keys
        mandatory_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        for key in mandatory_keys:
            self.assertIn(key, log_data, f"Mandatory log key '{key}' is missing from telemetry payload.")

        # Assert precise ISO 8601 UTC timestamp format (%Y-%m-%dT%H:%M:%SZ)
        timestamp = log_data["timestamp"]
        iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        self.assertTrue(
            re.match(iso_pattern, timestamp),
            f"Timestamp '{timestamp}' must strictly match the UTC ISO 8601 format %Y-%m-%dT%H:%M:%SZ."
        )

        # Assert specific logged fields
        self.assertEqual(log_data["correlation_id"], "test-correlation-123")
        self.assertEqual(log_data["step"], "test-step-validate")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 45)
        self.assertEqual(log_data["idempotency_key"], "V100_TEST")
        self.assertEqual(log_data["outcome_detail"], "Validation completed successfully")

if __name__ == '__main__':
    unittest.main()

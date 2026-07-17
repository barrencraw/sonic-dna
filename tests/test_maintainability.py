import unittest
import json
import re
import io
import contextlib
import datetime
from utils.dna_ui import DNAStatus, log_structured

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_members(self):
        """
        Verify that DNAStatus has the canonical terminal outcomes.
        """
        self.assertTrue(hasattr(DNAStatus, 'SUCCESS'))
        self.assertTrue(hasattr(DNAStatus, 'ERROR'))
        self.assertTrue(hasattr(DNAStatus, 'SKIPPED'))
        self.assertTrue(hasattr(DNAStatus, 'REFUSED'))

        self.assertEqual(DNAStatus.SUCCESS.value, 'success')
        self.assertEqual(DNAStatus.ERROR.value, 'error')
        self.assertEqual(DNAStatus.SKIPPED.value, 'skipped')
        self.assertEqual(DNAStatus.REFUSED.value, 'refused')

    def test_log_structured_fields_and_format(self):
        """
        Verify that log_structured emits logs in JSON format with the JSON_LOG: prefix
        and contains all mandatory fields.
        """
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=123,
                idempotency_key="TEST_KEY",
                outcome_detail="test detail",
                correlation_id="test_corr_id",
                actor_id="test_actor",
                chain_name="test_chain"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        # Mandatory fields
        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Mandatory field '{field}' is missing from structured log")

        # Check values
        self.assertEqual(log_data["correlation_id"], "test_corr_id")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "test_chain")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 123)
        self.assertEqual(log_data["idempotency_key"], "TEST_KEY")
        self.assertEqual(log_data["outcome_detail"], "test detail")

        # Timestamp format verification (%Y-%m-%dT%H:%M:%SZ)
        timestamp = log_data["timestamp"]
        # Match pattern like 2025-06-03T12:34:56Z
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        self.assertTrue(re.match(pattern, timestamp), f"Timestamp '{timestamp}' does not match ISO 8601 UTC format %Y-%m-%dT%H:%M:%SZ")

        # Parse timestamp to ensure it's valid
        dt = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        self.assertIsNotNone(dt)

if __name__ == '__main__':
    unittest.main()

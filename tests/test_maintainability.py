import unittest
import json
import io
import sys
from utils.dna_ui import (
    DNAStatus,
    log_structured,
    CONSEQUENCE_APPLIED_KEY,
    REFUSAL_REASON_KEY,
    NEXT_ACTION_HINT_KEY
)

class TestMaintainability(unittest.TestCase):
    def test_dna_status_lowercase_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_format(self):
        stdout_capture = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = stdout_capture
            log_entry = log_structured(
                correlation_id="test-corr-id",
                actor_id="test-actor",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=15,
                idempotency_key="VOL08900750712",
                outcome_detail={"key": "value"}
            )
        finally:
            sys.stdout = original_stdout

        output = stdout_capture.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        parsed = json.loads(json_str)

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, parsed)

        self.assertEqual(parsed["correlation_id"], "test-corr-id")
        self.assertEqual(parsed["actor_id"], "test-actor")
        self.assertEqual(parsed["outcome"], "success")

    def test_ui_message_keys_standardization(self):
        self.assertEqual(CONSEQUENCE_APPLIED_KEY, "Heat Accumulation")
        self.assertEqual(REFUSAL_REASON_KEY, "Thermal Lockout")
        self.assertEqual(NEXT_ACTION_HINT_KEY, "Wait for dissipation. The system is indifferent to your deadlines.")

if __name__ == '__main__':
    unittest.main()

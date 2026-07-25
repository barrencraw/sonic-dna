import unittest
import inspect
import io
import json
import contextlib
from utils import dna_ui

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature_parameter(self):
        """Verify run_batch has a correlation_id parameter."""
        sig = inspect.signature(dna_ui.run_batch)
        self.assertIn('correlation_id', sig.parameters)
        self.assertIsNone(sig.parameters['correlation_id'].default)

    def test_error_classes_inheritance(self):
        """Verify all custom errors inherit from DNAProcessingError."""
        self.assertTrue(issubclass(dna_ui.LedgerLoadError, dna_ui.DNAProcessingError))
        self.assertTrue(issubclass(dna_ui.RuleLoadError, dna_ui.DNAProcessingError))
        self.assertTrue(issubclass(dna_ui.PersistenceError, dna_ui.DNAProcessingError))

    def test_log_structured_emits_required_keys(self):
        """Verify log_structured outputs JSON with all mandatory fields."""
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            dna_ui.log_structured(
                correlation_id="test-correlation-123",
                step="test-step",
                outcome="success",
                latency_ms=42,
                idempotency_key="VOL123",
                outcome_detail="Tested successfully"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data)

        self.assertEqual(log_data["correlation_id"], "test-correlation-123")
        self.assertEqual(log_data["step"], "test-step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 42)
        self.assertEqual(log_data["idempotency_key"], "VOL123")
        self.assertEqual(log_data["outcome_detail"], "Tested successfully")
        self.assertEqual(log_data["actor_id"], "system")
        self.assertEqual(log_data["chain_name"], "DNA Batch Parsing")

if __name__ == '__main__':
    unittest.main()

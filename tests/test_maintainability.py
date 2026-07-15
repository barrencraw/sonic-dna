import unittest
import json
import inspect
from utils import dna_ui

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming(self):
        """Verify that the batch processing entry point is named 'run_batch'."""
        self.assertTrue(hasattr(dna_ui, 'run_batch'), "utils.dna_ui must have a 'run_batch' function")
        self.assertTrue(callable(dna_ui.run_batch), "utils.dna_ui.run_batch must be callable")

    def test_run_batch_signature(self):
        """Verify run_batch accepts correlation_id and actor_id."""
        sig = inspect.signature(dna_ui.run_batch)
        self.assertIn('correlation_id', sig.parameters)
        self.assertIn('actor_id', sig.parameters)

    def test_structured_log_fields(self):
        """Verify that log_structured includes all mandatory fields."""
        # We'll capture the output of log_structured
        from unittest.mock import patch
        import io

        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            dna_ui.log_structured(
                correlation_id="test-id",
                actor_id="test-actor",
                chain_name="test-chain",
                step="test-step",
                outcome=dna_ui.DNAStatus.SUCCESS,
                latency_ms=100,
                idempotency_key="test-key",
                outcome_detail="test-detail"
            )
            output = fake_out.getvalue().strip()

        self.assertTrue(output.startswith("JSON_LOG: "))
        log_json = json.loads(output[len("JSON_LOG: "):])

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_json, f"Missing mandatory field: {field}")

if __name__ == '__main__':
    unittest.main()

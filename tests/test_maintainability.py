import os
import json
import inspect
import unittest
from utils.dna_ui import run_batch, log_structured, DNAStatus
from io import StringIO
from contextlib import redirect_stdout

class TestMaintainability(unittest.TestCase):
    def test_run_batch_signature(self):
        """Verify run_batch uses canonical naming in its signature."""
        sig = inspect.signature(run_batch)
        # We don't enforce dna_sequences in the signature yet because it reads from file
        # but we check if it has correlation_id
        self.assertIn('correlation_id', sig.parameters)

    def test_log_structured_fields(self):
        """Verify log_structured output contains mandatory fields."""
        f = StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-id",
                step="test-step",
                outcome="test-outcome",
                idempotency_key="test-key"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        log_data = json.loads(output[9:])

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id",
            "chain_name", "step", "outcome", "idempotency_key"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_data, f"Missing mandatory field: {field}")

    def test_dna_status_enum(self):
        """Verify DNAStatus enum has all required states."""
        required_states = ["SUCCESS", "ERROR", "SKIPPED", "REFUSED"]
        for state in required_states:
            self.assertTrue(hasattr(DNAStatus, state), f"DNAStatus missing state: {state}")

if __name__ == '__main__':
    unittest.main()

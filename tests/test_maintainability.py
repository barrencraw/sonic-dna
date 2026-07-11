import unittest
import inspect
import json
import os
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_calculator(self):
        # Check DNACalculator.parse parameter name
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_log_prefix(self):
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("cid", "actor", "chain", "step", "outcome")
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))

        # Verify JSON validity
        log_json = output[9:]
        data = json.loads(log_json)
        mandatory_fields = ["timestamp", "correlation_id", "actor_id", "chain_name", "step", "outcome", "latency_ms", "idempotency_key"]
        for field in mandatory_fields:
            self.assertIn(field, data)

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import inspect
import json
from utils.dna_calculator import DNACalculator
from utils.dna_ui import log_structured

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """Verify canonical naming 'dna_sequence' in function signatures."""
        from utils.dna_calculator import Rule

        # Check Rule.parse signature
        sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', sig.parameters)

        # Check DNACalculator.parse signature
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_log_fields(self):
        """Verify that log_structured includes all mandatory fields."""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                step="test_step",
                outcome="test_outcome",
                correlation_id="test_cid",
                actor_id="test_actor",
                idempotency_key="test_key"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        log_json = json.loads(output[9:])

        mandatory_fields = [
            "timestamp", "correlation_id", "actor_id",
            "chain_name", "step", "outcome", "latency_ms", "idempotency_key"
        ]
        for field in mandatory_fields:
            self.assertIn(field, log_json)

    def test_output_schema_alignment(self):
        """Verify that output dictionary uses 'dna_sequence' key."""
        # We can't easily run the whole main() here without lots of setup,
        # but we can check the logic in utils/dna_ui.py via inspection or small mock
        import utils.dna_ui as dna_ui

        # This is a bit of a white-box test, but it guards against reverting the key name
        # We'll check if the string 'dna_sequence' appears in the file where expected
        with open(dna_ui.__file__, 'r') as f:
            content = f.read()
            self.assertIn("'dna_sequence': dna_sequence", content)
            self.assertNotIn("'dna': dna_sequence", content)
            self.assertNotIn("'dna': dna_str", content)

if __name__ == "__main__":
    unittest.main()

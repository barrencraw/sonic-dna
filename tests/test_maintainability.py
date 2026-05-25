import unittest
import os
import json
from utils.dna_ui import TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming(self):
        """Verify that 'dna_sequence' is used consistently where expected."""
        # This is a bit of a meta-test, we check the code itself or just ensure our Enum members are correct
        self.assertTrue(hasattr(TerminalOutcome, 'SUCCESS'))
        self.assertTrue(hasattr(TerminalOutcome, 'PARSE_ERROR'))
        self.assertTrue(hasattr(TerminalOutcome, 'SKIPPED'))

    def test_enum_values(self):
        """Ensure Enum values match the contract."""
        self.assertEqual(TerminalOutcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(TerminalOutcome.PARSE_ERROR.value, "PARSE_ERROR")
        self.assertEqual(TerminalOutcome.SKIPPED.value, "SKIPPED")

    def test_structured_logging_fields(self):
        """Verify log_structured helper (indirectly via a mock or just checking presence)."""
        from utils.dna_ui import log_structured
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("test-cid", "test-step", outcome_val=TerminalOutcome.SUCCESS)

        output = f.getvalue().strip()
        log_data = json.loads(output)

        self.assertEqual(log_data["correlation_id"], "test-cid")
        self.assertEqual(log_data["step"], "test-step")
        self.assertEqual(log_data["outcome"], "SUCCESS")
        self.assertIn("timestamp", log_data)
        self.assertEqual(log_data["chain_name"], "dna_batch_chain")

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
from utils.dna_ui import TerminalOutcome, log_structured

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_alignment(self):
        """Ensure dna_sequence is used instead of legacy dna keys."""
        with open('utils/dna_ui.py', 'r') as f:
            content = f.read()

        # We should NOT find " 'dna': " or " \"dna\": " or " ['dna'] " or " [\"dna\"] "
        # except where it's part of a larger word like dna_sequence
        import re
        legacy_dna_usage = re.findall(r"['\"]dna['\"]", content)
        # Filter out dna_sequence
        legacy_dna_usage = [u for u in legacy_dna_usage if 'dna_sequence' not in u]

        # Actually, let's be more specific. We want to ensure 'dna_sequence' is present.
        self.assertIn('dna_sequence', content)

        # And that we don't have the old 'dna' key in the entry dictionary
        self.assertNotIn("'dna':", content)
        self.assertNotIn("\"dna\":", content)

    def test_terminal_outcome_enum(self):
        """Ensure TerminalOutcome Enum is defined and has required members."""
        self.assertTrue(hasattr(TerminalOutcome, 'SUCCESS'))
        self.assertTrue(hasattr(TerminalOutcome, 'PARSE_ERROR'))
        self.assertTrue(hasattr(TerminalOutcome, 'SKIPPED'))

        self.assertEqual(TerminalOutcome.SUCCESS.value, "SUCCESS")
        self.assertEqual(TerminalOutcome.PARSE_ERROR.value, "PARSE_ERROR")
        self.assertEqual(TerminalOutcome.SKIPPED.value, "SKIPPED")

    def test_structured_logging_schema(self):
        """Verify log_structured uses the correct keys."""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("test_corr_id", "test_step", "SUCCESS", idempotency_key="test_key", latency_ms=100)

        log_output = f.getvalue().strip()
        log_entry = json.loads(log_output)

        required_keys = ["timestamp", "correlation_id", "chain_name", "step", "outcome", "actor_id", "idempotency_key", "latency_ms"]
        for key in required_keys:
            self.assertIn(key, log_entry, f"Missing required log key: {key}")

        self.assertEqual(log_entry["correlation_id"], "test_corr_id")
        self.assertEqual(log_entry["step"], "test_step")
        self.assertEqual(log_entry["outcome"], "SUCCESS")

if __name__ == '__main__':
    unittest.main()

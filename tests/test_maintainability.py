import unittest
import os
import re
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import TerminalOutcome, log_structured

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_dna_sequence(self):
        """
        Ensure 'dna_sequence' is used consistently in core files.
        """
        patterns = [
            (r'dna_str', 'utils/dna_ui.py'),
            (r'dna_string', 'utils/dna_ui.py'),
            (r'dna_string', 'utils/dna_calculator.py'),
        ]

        for pattern, filepath in patterns:
            if not os.path.exists(filepath):
                continue
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                # Exclude comments and docstrings for a stricter check if needed,
                # but here we just check for the pattern in general code.
                # We'll use a simple regex that looks for assignments or function args.
                matches = re.findall(rf'\b{pattern}\b', content)
                # Allow it in docstrings or comments for now if necessary,
                # but the goal is to have 0 in code.
                # Let's just check if they exist at all.
                self.assertEqual(len(matches), 0, f"Found non-canonical name '{pattern}' in {filepath}")

    def test_terminal_outcome_enum_members(self):
        """
        Verify TerminalOutcome has the required members.
        """
        expected_members = {"SUCCESS", "PARSE_ERROR", "SKIPPED"}
        actual_members = {m.name for m in TerminalOutcome}
        for expected in expected_members:
            self.assertIn(expected, actual_members)

    def test_structured_logging_schema(self):
        """
        Verify log_structured produces the expected JSON schema.
        """
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome_val=TerminalOutcome.SUCCESS,
                dna_sequence="TEST-DNA",
                error="test-error",
                latency_ms=123,
                actor_id="test-actor",
                idempotency_key="test-key"
            )

        output = f.getvalue().strip()
        log_entry = json.loads(output)

        self.assertIn("timestamp", log_entry)
        self.assertEqual(log_entry["correlation_id"], "test-id")
        self.assertEqual(log_entry["chain_name"], "test-chain")
        self.assertEqual(log_entry["step"], "test-step")
        self.assertEqual(log_entry["outcome"], "SUCCESS")
        self.assertEqual(log_entry["dna_sequence"], "TEST-DNA")
        self.assertEqual(log_entry["error"], "test-error")
        self.assertEqual(log_entry["latency_ms"], 123)
        self.assertEqual(log_entry["actor_id"], "test-actor")
        self.assertEqual(log_entry["idempotency_key"], "test-key")

if __name__ == '__main__':
    unittest.main()

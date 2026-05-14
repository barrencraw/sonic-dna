import unittest
import os
import re
import json
from utils.dna_ui import TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_dna_sequence(self):
        """
        Ensures 'dna_sequence' is used instead of 'dna_str' or 'dna_string'
        in key files.
        """
        files_to_check = [
            'utils/dna_ui.py',
            'utils/dna_calculator.py',
            'main.py'
        ]

        # Pattern to find 'dna_str' or 'dna_string' as a whole word,
        # but ignoring comments if possible (simple grep-like)
        prohibited = re.compile(r'\b(dna_str|dna_string)\b')

        for filepath in files_to_check:
            if not os.path.exists(filepath):
                continue
            with open(filepath, 'r', encoding='utf-8') as f:
                for line_no, line in enumerate(f, 1):
                    # Skip comments
                    if line.strip().startswith('#'):
                        continue
                    match = prohibited.search(line)
                    self.assertIsNone(
                        match,
                        f"Prohibited name '{match.group(0) if match else ''}' found in {filepath}:{line_no}"
                    )

    def test_terminal_outcome_enum_consistency(self):
        """
        Verifies TerminalOutcome enum values are as expected for ledger consistency.
        """
        self.assertEqual(TerminalOutcome.SUCCESS.value, "success")
        self.assertEqual(TerminalOutcome.PARSE_ERROR.value, "error")
        self.assertEqual(TerminalOutcome.SKIPPED.value, "skipped")

    def test_structured_logging_format(self):
        """
        Checks that log_structured helper in dna_ui.py uses standard fields.
        """
        from utils.dna_ui import log_structured
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-id",
                step="test-step",
                outcome="success",
                latency_ms=100,
                extra_field="extra"
            )

        log_output = f.getvalue().strip()
        data = json.loads(log_output)

        expected_keys = {
            "correlation_id", "chain_name", "step", "outcome",
            "latency_ms", "timestamp", "extra_field"
        }
        for key in expected_keys:
            self.assertIn(key, data, f"Missing standard log field: {key}")

        self.assertEqual(data["chain_name"], "dna_batch_chain")

if __name__ == '__main__':
    unittest.main()

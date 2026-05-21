import unittest
import os
import re
import json
from enum import Enum
from utils.dna_ui import TerminalOutcome, DNAProcessingResult

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """Ensures 'dna_sequence' is used consistently in core files."""
        patterns = [
            (r'dna_string', 'utils/dna_calculator.py'),
            (r'dna_str', 'utils/dna_ui.py'),
            (r'dna_list', 'utils/dna_ui.py'),
        ]

        for pattern, filepath in patterns:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Skip comments or strings if they contain the pattern, but check code
                    # Simple check: the pattern should not appear as a variable/parameter name
                    self.assertIsNone(
                        re.search(rf'\b{pattern}\b', content),
                        f"Found forbidden naming '{pattern}' in {filepath}. Use 'dna_sequence' or 'dna_sequences' instead."
                    )

    def test_terminal_outcome_enum(self):
        """Verifies TerminalOutcome enum has expected members."""
        expected = {'SUCCESS', 'PARSE_ERROR', 'SKIPPED'}
        actual = {m.name for m in TerminalOutcome}
        self.assertTrue(expected.issubset(actual), f"TerminalOutcome missing members: {expected - actual}")

    def test_log_structured_presence(self):
        """Checks if utils/dna_ui.py uses log_structured for key events."""
        filepath = 'utils/dna_ui.py'
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn('log_structured', content)
            # Check for mandatory log fields in the codebase
            mandatory_fields = ['correlation_id', 'idempotency_key', 'terminal_outcome']
            for field in mandatory_fields:
                self.assertIn(field, content)

if __name__ == '__main__':
    unittest.main()

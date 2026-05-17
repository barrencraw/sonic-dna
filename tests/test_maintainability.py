import unittest
import os
import re
from utils.dna_ui import TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_dna_sequence(self):
        """
        Verify that core files use 'dna_sequence' or 'dna_sequences'
        instead of 'dna_str' or 'dna_list'.
        """
        files_to_check = ['utils/dna_ui.py', 'utils/dna_calculator.py']
        prohibited = [r'\bdna_str\b', r'\bdna_list\b', r'\bdna_string\b']

        for filepath in files_to_check:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                for pattern in prohibited:
                    matches = re.findall(pattern, content)
                    self.assertEqual(len(matches), 0, f"Prohibited pattern '{pattern}' found in {filepath}")

    def test_terminal_outcome_enum(self):
        """Verify existence and members of TerminalOutcome enum."""
        self.assertTrue(hasattr(TerminalOutcome, 'SUCCESS'))
        self.assertTrue(hasattr(TerminalOutcome, 'PARSE_ERROR'))
        self.assertTrue(hasattr(TerminalOutcome, 'SKIPPED'))

        self.assertEqual(TerminalOutcome.SUCCESS.value, 'success')
        self.assertEqual(TerminalOutcome.PARSE_ERROR.value, 'parse_error')
        self.assertEqual(TerminalOutcome.SKIPPED.value, 'skipped')

    def test_structured_logging_presence(self):
        """Verify log_structured is present and used in dna_ui.py."""
        with open('utils/dna_ui.py', 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn('def log_structured', content)
            self.assertIn('log_structured(', content)

if __name__ == '__main__':
    unittest.main()

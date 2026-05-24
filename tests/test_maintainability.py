import unittest
import os
import re
from utils.dna_ui import TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """Verify that 'dna_sequence' or 'dna_sequences' is used in core files."""
        files_to_check = ['utils/dna_ui.py', 'utils/dna_calculator.py']
        # Canonical pattern: dna_sequence or dna_sequences
        # We want to avoid dna_str, dna_string, dna_list
        forbidden = [r'dna_str\b', r'dna_string\b', r'dna_list\b']

        for filepath in files_to_check:
            with open(filepath, 'r') as f:
                content = f.read()
                for pattern in forbidden:
                    matches = re.findall(pattern, content)
                    self.assertEqual(len(matches), 0, f"Found forbidden pattern '{pattern}' in {filepath}")

    def test_terminal_outcome_enum(self):
        """Verify TerminalOutcome Enum has required members."""
        expected_members = ['SUCCESS', 'PARSE_ERROR', 'SKIPPED']
        for member in expected_members:
            self.assertTrue(hasattr(TerminalOutcome, member), f"TerminalOutcome missing member {member}")

    def test_structured_logging_presence(self):
        """Verify log_structured is called in dna_ui.py."""
        with open('utils/dna_ui.py', 'r') as f:
            content = f.read()
            self.assertIn('log_structured', content)
            self.assertIn('correlation_id', content)
            self.assertIn('idempotency_key', content)

if __name__ == '__main__':
    unittest.main()

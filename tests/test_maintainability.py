import unittest
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_dna_sequence(self):
        """
        Ensure DNACalculator.parse uses 'dna_sequence' as parameter name.
        """
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse must have 'dna_sequence' parameter")

    def test_terminal_outcome_enum_members(self):
        """
        Ensure TerminalOutcome has required members.
        """
        expected = {'SUCCESS', 'PARSE_ERROR', 'SKIPPED'}
        actual = {m.name for m in TerminalOutcome}
        for item in expected:
            self.assertIn(item, actual, f"TerminalOutcome missing member: {item}")

if __name__ == '__main__':
    unittest.main()

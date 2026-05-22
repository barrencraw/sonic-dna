import unittest
import inspect
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_calculator(self):
        """Verify DNACalculator.parse uses 'dna_sequence' as parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)
        self.assertNotIn('dna_string', sig.parameters)

    def test_naming_alignment_rule(self):
        """Verify Rule.parse uses 'dna_sequence' as parameter name."""
        sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', sig.parameters)
        self.assertNotIn('dna_string', sig.parameters)

    def test_terminal_outcome_enum(self):
        """Verify TerminalOutcome Enum has required members."""
        expected_members = {'SUCCESS', 'PARSE_ERROR', 'SKIPPED'}
        actual_members = {m.name for m in TerminalOutcome}
        for member in expected_members:
            self.assertIn(member, actual_members)

    def test_structured_logging_keys(self):
        """Verify log_structured helper exists and has correct signature."""
        from utils.dna_ui import log_structured
        sig = inspect.signature(log_structured)
        required_params = {'correlation_id', 'chain_name', 'step', 'outcome_val'}
        for param in required_params:
            self.assertIn(param, sig.parameters)

if __name__ == '__main__':
    unittest.main()

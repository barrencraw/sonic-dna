import unittest
import os
import json
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_in_signatures(self):
        """Ensure core functions use 'dna_sequence' in their signature."""
        # Check DNACalculator.parse
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse should have 'dna_sequence' parameter")

    def test_terminal_outcome_enum_consistency(self):
        """Ensure TerminalOutcome Enum has required members."""
        expected_members = {'SUCCESS', 'PARSE_ERROR', 'SKIPPED'}
        actual_members = set(TerminalOutcome.__members__.keys())
        self.assertTrue(expected_members.issubset(actual_members), f"Missing TerminalOutcome members: {expected_members - actual_members}")

    def test_ledger_outcome_values(self):
        """Verify that any existing ledger entries use valid TerminalOutcome values."""
        ledger_path = os.path.join(os.getcwd(), 'data', 'processed_ledger.json')
        if os.path.exists(ledger_path):
            with open(ledger_path, 'r') as f:
                ledger = json.load(f)

            valid_outcomes = {member.value for member in TerminalOutcome}
            for dna_seq, entry in ledger.items():
                outcome = entry.get('terminal_outcome')
                self.assertIn(outcome, valid_outcomes, f"Invalid terminal_outcome '{outcome}' for sequence '{dna_seq}'")

if __name__ == '__main__':
    unittest.main()

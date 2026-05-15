import unittest
import os
import json
import inspect
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import main as run_batch, TerminalOutcome, DNAProcessingResult

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment(self):
        """
        Ensure 'dna_sequence' is used in core parsing methods.
        """
        # DNACalculator.parse(self, dna_sequence)
        sig_calc = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig_calc.parameters)

        # Rule.parse(self, dna_sequence)
        sig_rule = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', sig_rule.parameters)

    def test_explicit_terminal_states(self):
        """
        Ensure TerminalOutcome and DNAProcessingResult are correctly defined and used.
        """
        self.assertTrue(hasattr(TerminalOutcome, 'SUCCESS'))
        self.assertTrue(hasattr(TerminalOutcome, 'PARSE_ERROR'))
        self.assertTrue(hasattr(TerminalOutcome, 'SKIPPED'))

        sig_res = inspect.signature(DNAProcessingResult)
        self.assertIn('dna_sequence', sig_res.parameters)
        self.assertIn('terminal_outcome', sig_res.parameters)

    def test_structured_logging_format(self):
        """
        Ensure log_structured exists and has required fields.
        """
        from utils.dna_ui import log_structured
        sig_log = inspect.signature(log_structured)
        self.assertIn('step', sig_log.parameters)
        self.assertIn('outcome', sig_log.parameters)
        self.assertIn('correlation_id', sig_log.parameters)
        self.assertIn('chain_name', sig_log.parameters)
        self.assertIn('latency_ms', sig_log.parameters)

if __name__ == '__main__':
    unittest.main()

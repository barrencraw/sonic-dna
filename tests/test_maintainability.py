import unittest
import inspect
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import DNAStatus, log_structured, main as run_batch

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_dna_sequence(self):
        """Verify that dna_sequence is used as the canonical parameter name."""
        # Check Rule.parse
        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must have 'dna_sequence' parameter")

        # Check DNACalculator.parse
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must have 'dna_sequence' parameter")

    def test_explicit_terminal_states(self):
        """Verify that DNAStatus enum defines the required terminal states."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

    def test_structured_logging_format(self):
        """Verify that log_structured emits correctly formatted JSON logs."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("Test message", step="test_step", outcome="test_outcome", correlation_id="test_cid")

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "), "Log must start with 'JSON_LOG: ' prefix")

        log_json = json.loads(output.replace("JSON_LOG: ", ""))
        self.assertEqual(log_json['message'], "Test message")
        self.assertEqual(log_json['step'], "test_step")
        self.assertEqual(log_json['outcome'], "test_outcome")
        self.assertEqual(log_json['correlation_id'], "test_cid")
        self.assertIn('timestamp', log_json)

    def test_ui_main_traceability(self):
        """Verify that run_batch (dna_ui.main) accepts traceability parameters."""
        main_sig = inspect.signature(run_batch)
        self.assertIn('correlation_id', main_sig.parameters)
        self.assertIn('actor_id', main_sig.parameters)

if __name__ == '__main__':
    unittest.main()

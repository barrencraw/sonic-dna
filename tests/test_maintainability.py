import inspect
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_calculator import DNACalculator, RuleParseError
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    run_batch
)

class TestMaintainability(unittest.TestCase):

    def test_naming_alignment_dna_sequence(self):
        """Verify canonical parameter name and docstring in DNACalculator.parse."""
        sig = inspect.signature(DNACalculator.parse)
        params = list(sig.parameters.keys())
        self.assertIn("dna_sequence", params, "DNACalculator.parse parameter must be 'dna_sequence'")

        doc = inspect.getdoc(DNACalculator.parse)
        self.assertIsNotNone(doc)
        self.assertIn("DNA sequence", doc, "Docstring must use canonical term 'DNA sequence'")

    def test_typed_error_hierarchy(self):
        """Verify typed error inheritance under DNAProcessingError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))

    def test_structured_log_fields_presence(self):
        """Verify structured log output contains all required observability keys."""
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(test_dir)
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("V100\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            with patch('sys.stdout', new=io.StringIO()) as fake_out:
                run_batch(correlation_id="test_corr_123", actor_id="test_actor")
                output = fake_out.getvalue()

            required_keys = [
                "correlation_id",
                "chain_name",
                "step",
                "outcome",
                "latency_ms",
                "actor_id",
                "idempotency_key"
            ]

            log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]
            self.assertGreater(len(log_lines), 0, "Structured logs should be emitted")

            for line in log_lines:
                json_str = line.replace("JSON_LOG: ", "")
                log_data = json.loads(json_str)
                for req_key in required_keys:
                    self.assertIn(req_key, log_data, f"Log entry missing required field '{req_key}'")

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

    def test_explicit_terminal_states_in_ledger(self):
        """Verify ledger stores standardized terminal outcome status."""
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(test_dir)
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("V100\nINVALID_SEQ\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            run_batch()

            ledger_file = os.path.join(test_dir, 'data', 'processed_ledger.json')
            self.assertTrue(os.path.exists(ledger_file))

            with open(ledger_file, 'r') as f:
                ledger = json.load(f)

            self.assertIn("V100", ledger)
            self.assertEqual(ledger["V100"]["terminal_outcome"], DNAStatus.SUCCESS)

            self.assertIn("INVALID_SEQ", ledger)
            self.assertEqual(ledger["INVALID_SEQ"]["terminal_outcome"], DNAStatus.ERROR)

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

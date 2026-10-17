import unittest
import os
import json
import io
import shutil
import tempfile
import sys
from unittest.mock import patch

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    load_ledger,
    log_structured,
    run_batch
)
from utils.dna_calculator import DNACalculator, Rule

class TestMaintainability(unittest.TestCase):

    def test_dnastatus_enum_values(self):
        """Verify DNAStatus string enum values are strictly lowercase and standard."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_typed_exception_hierarchy(self):
        """Verify the typed exception taxonomy inheritance."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_load_ledger_raises_ledger_load_error_on_corrupted_file(self):
        """Verify load_ledger raises LedgerLoadError when given invalid JSON."""
        temp_dir = tempfile.mkdtemp()
        try:
            corrupt_file = os.path.join(temp_dir, 'corrupt_ledger.json')
            with open(corrupt_file, 'w') as f:
                f.write("{ invalid_json: ")

            with self.assertRaises(LedgerLoadError):
                load_ledger(corrupt_file)
        finally:
            shutil.rmtree(temp_dir)

    def test_structured_log_format_and_schema(self):
        """Verify log_structured emits JSON_LOG with all required mandatory keys."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test_actor",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                idempotency_key="V100",
                outcome_detail="Parsed volume level 100"
            )
        finally:
            sys.stdout = sys.__stdout__

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG: "))

        json_str = output_str[len("JSON_LOG: "):]
        log_data = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_data, f"Mandatory log key '{key}' missing from structured log")

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["outcome"], "success")

    def test_naming_alignment_and_backward_compatible_keys(self):
        """Verify parameter naming alignment in DNACalculator and output file keys."""
        import inspect
        sig_calculator = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", sig_calculator.parameters)

        sig_rule = inspect.signature(Rule.parse)
        self.assertIn("dna_sequence", sig_rule.parameters)

        # Test batch processing produces both canonical 'dna_sequence' and legacy 'dna' keys
        temp_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        try:
            data_dir = os.path.join(temp_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
            rules_dir = os.path.join(temp_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("V100\n")

            run_batch(correlation_id="test-batch-run")

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r') as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            self.assertIn("dna_sequence", data[0])
            self.assertIn("dna", data[0])
            self.assertEqual(data[0]["dna_sequence"], "V100")
            self.assertEqual(data[0]["dna"], "V100")

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(temp_dir)

if __name__ == '__main__':
    unittest.main()

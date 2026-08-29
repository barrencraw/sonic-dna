import inspect
import json
import os
import shutil
import tempfile
import unittest
import io
import sys
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)


class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_parameter(self):
        """Verify canonical parameter name 'dna_sequence' in DNACalculator.parse and Rule.parse."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must use parameter 'dna_sequence'")

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must use parameter 'dna_sequence'")

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed error classification hierarchy under DNAProcessingError and PersistenceError."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_terminal_status_enum_values(self):
        """Verify DNAStatus enum uses exact lowercase terminal state strings."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_schema(self):
        """Verify log_structured emits JSON_LOG with all mandatory observability fields."""
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            log_structured(
                correlation_id="test-corr-id-123",
                actor_id="test_actor",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                idempotency_key="VOL100",
                outcome_detail="Test execution detail"
            )
        finally:
            sys.stdout = sys.__stdout__

        log_str = captured_output.getvalue().strip()
        self.assertTrue(log_str.startswith("JSON_LOG: "))

        json_part = log_str[len("JSON_LOG: "):]
        log_dict = json.loads(json_part)

        required_keys = [
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key",
            "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, log_dict, f"Structured log missing required key: '{key}'")

        self.assertEqual(log_dict["correlation_id"], "test-corr-id-123")
        self.assertEqual(log_dict["actor_id"], "test_actor")
        self.assertEqual(log_dict["chain_name"], "dna_batch_parser")
        self.assertEqual(log_dict["outcome"], "success")

    def test_output_contains_canonical_dna_sequence_key(self):
        """Verify output dictionary contains canonical 'dna_sequence' key."""
        test_dir = tempfile.mkdtemp()
        try:
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            with open(os.path.join(raw_dir, 'toSequence.txt'), 'w') as f:
                f.write("VOL100\n")

            with open(os.path.join(rules_dir, 'rules_Volume.json'), 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="test-run")
            finally:
                os.chdir(old_cwd)

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r') as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            self.assertIn("dna_sequence", data[0], "JSON output entry must contain canonical 'dna_sequence' key")
            self.assertEqual(data[0]["dna_sequence"], "VOL100")
        finally:
            shutil.rmtree(test_dir)


if __name__ == '__main__':
    unittest.main()

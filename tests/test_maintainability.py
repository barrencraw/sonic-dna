import inspect
import json
import os
import unittest
import tempfile
import shutil
from unittest.mock import patch
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)


class TestMaintainability(unittest.TestCase):

    def test_dna_calculator_parameter_naming(self):
        """Regression guard: parse() must accept 'dna_sequence' parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse parameter should be named 'dna_sequence'")

    def test_dnastatus_lowercase_values(self):
        """Regression guard: DNAStatus enum must use lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

        self.assertTrue(DNAStatus.SUCCESS.success)
        self.assertTrue(DNAStatus.ERROR.error)
        self.assertTrue(DNAStatus.SKIPPED.skipped)
        self.assertTrue(DNAStatus.REFUSED.refused)

    def test_exception_taxonomy_hierarchy(self):
        """Regression guard: typed exception classes must follow the defined hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_keys(self):
        """Regression guard: log_structured must contain all required schema keys."""
        log_entry = log_structured(
            correlation_id="test_cid",
            actor_id="test_actor",
            chain_name="test_chain",
            step="test_step",
            outcome="success",
            latency_ms=12.34,
            idempotency_key="test_key",
            outcome_detail="test_detail"
        )
        required_keys = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }
        self.assertTrue(required_keys.issubset(log_entry.keys()))
        self.assertEqual(log_entry["correlation_id"], "test_cid")
        self.assertEqual(log_entry["actor_id"], "test_actor")
        self.assertEqual(log_entry["outcome"], "success")

    def test_output_contains_canonical_and_legacy_keys(self):
        """Regression guard: processed output must contain both dna_sequence and legacy dna keys."""
        test_dir = tempfile.mkdtemp()
        try:
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("VOL10000000000\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            result = run_batch(project_root=test_dir)
            self.assertEqual(result["status"], "success")

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r') as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            self.assertIn('dna_sequence', data[0])
            self.assertIn('dna', data[0])
            self.assertEqual(data[0]['dna_sequence'], "VOL10000000000")
            self.assertEqual(data[0]['dna'], "VOL10000000000")
        finally:
            shutil.rmtree(test_dir)


if __name__ == '__main__':
    unittest.main()

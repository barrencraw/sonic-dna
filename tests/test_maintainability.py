import os
import json
import io
import sys
import shutil
import tempfile
import unittest
import inspect

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
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup minimal directories
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Create a rule
        rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_sequence_naming_and_compatibility(self):
        """Verify method signature uses dna_sequence and output contains both legacy and canonical keys."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse parameter should be named dna_sequence")

        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch(correlation_id="test_corr_id", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r') as f:
            records = json.load(f)

        self.assertEqual(len(records), 1)
        self.assertIn('dna', records[0], "Legacy 'dna' key missing")
        self.assertIn('dna_sequence', records[0], "Canonical 'dna_sequence' key missing")
        self.assertEqual(records[0]['dna'], "VOL100")
        self.assertEqual(records[0]['dna_sequence'], "VOL100")

    def test_typed_exception_hierarchy(self):
        """Verify explicit typed error classification inheritance hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dnastatus_enum_values(self):
        """Verify DNAStatus enum exposes required lowercase terminal state strings."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_schema(self):
        """Verify log_structured outputs JSON with all required trace fields."""
        captured_output = io.StringIO()
        original_stdout = sys.stdout

        try:
            sys.stdout = captured_output
            log_structured(
                correlation_id="corr-123",
                chain_name="dna_batch_parse",
                step="test_step",
                outcome="success",
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL100",
                outcome_detail="test detail"
            )
        finally:
            sys.stdout = original_stdout

        log_str = captured_output.getvalue().strip()
        self.assertTrue(log_str.startswith("JSON_LOG: "))

        json_part = log_str[len("JSON_LOG: "):]
        data = json.loads(json_part)

        required_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key", "outcome_detail"
        }
        for k in required_keys:
            self.assertIn(k, data, f"Required log key '{k}' missing from structured log payload")

        self.assertEqual(data["correlation_id"], "corr-123")
        self.assertEqual(data["chain_name"], "dna_batch_parse")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 12.34)
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["idempotency_key"], "VOL100")
        self.assertEqual(data["outcome_detail"], "test detail")

if __name__ == '__main__':
    unittest.main()

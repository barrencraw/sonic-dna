import unittest
import os
import json
import inspect
import tempfile
import shutil
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

class TestMaintainabilityAndSignal(unittest.TestCase):

    def test_naming_alignment(self):
        """Verify canonical name dna_sequence is used in parse signatures."""
        calc_params = list(inspect.signature(DNACalculator.parse).parameters.keys())
        rule_params = list(inspect.signature(Rule.parse).parameters.keys())

        self.assertIn("dna_sequence", calc_params)
        self.assertIn("dna_sequence", rule_params)

    def test_terminal_states_enum(self):
        """Verify DNAStatus enum defines explicit, lower-case terminal outcomes."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed error classification and inheritance."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_keys_presence(self):
        """Verify log_structured outputs all required telemetry fields."""
        log_entry = log_structured(
            event_type="test_event",
            correlation_id="test-corr-123",
            actor_id="test_actor",
            step="unit_test",
            outcome=DNAStatus.SUCCESS,
            latency_ms=12.34,
            idempotency_key="VOL100"
        )

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
            self.assertIn(key, log_entry, f"Missing required telemetry key: {key}")

        self.assertEqual(log_entry["correlation_id"], "test-corr-123")
        self.assertEqual(log_entry["actor_id"], "test_actor")
        self.assertEqual(log_entry["chain_name"], "dna_batch_parser")
        self.assertEqual(log_entry["outcome"], "success")
        self.assertEqual(log_entry["latency_ms"], 12.34)
        self.assertEqual(log_entry["idempotency_key"], "VOL100")

    def test_backward_compatibility_output_keys(self):
        """Verify batch output entries contain both 'dna' and 'dna_sequence' keys."""
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
                f.write("V050\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)

            try:
                run_batch(correlation_id="test-run", actor_id="test_runner")

                json_out_path = os.path.join(output_dir, 'toSequence_parsed.json')
                self.assertTrue(os.path.exists(json_out_path))

                with open(json_out_path, 'r') as f:
                    data = json.load(f)

                self.assertEqual(len(data), 1)
                self.assertIn('dna', data[0])
                self.assertIn('dna_sequence', data[0])
                self.assertEqual(data[0]['dna'], 'V050')
                self.assertEqual(data[0]['dna_sequence'], 'V050')

            finally:
                os.chdir(old_cwd)

        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

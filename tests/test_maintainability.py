import os
import json
import shutil
import tempfile
import unittest
import io
from contextlib import redirect_stdout
import inspect

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
    """
    Regression guard tests to prevent backsliding on:
    1. Naming alignment (canonical dna_sequence)
    2. Explicit terminal status enums and typed error classification
    3. Observability hygiene (structured JSON log fields)
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a minimal Volume rule
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_in_calculator_and_rule(self):
        """Verify canonical parameter naming 'dna_sequence' in DNACalculator and Rule."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", calc_sig.parameters, "DNACalculator.parse parameter should be dna_sequence")

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn("dna_sequence", rule_sig.parameters, "Rule.parse parameter should be dna_sequence")

    def test_naming_alignment_in_outputs(self):
        """Verify batch parse outputs emit both canonical 'dna_sequence' and backward-compatible 'dna'."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertIn("dna_sequence", data[0], "JSON output payload must contain canonical 'dna_sequence'")
        self.assertIn("dna", data[0], "JSON output payload must maintain backward-compatible 'dna'")
        self.assertEqual(data[0]["dna_sequence"], "VOL100")
        self.assertEqual(data[0]["dna"], "VOL100")

    def test_error_classification_hierarchy(self):
        """Verify typed error taxonomy inheritance."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_explicit_terminal_states(self):
        """Verify DNAStatus enum defines clear terminal states matching legacy lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_observability_structured_log_hygiene(self):
        """Verify structured logging schema emits all required fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.345,
                actor_id="test_actor",
                idempotency_key="VOL100"
            )

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_part = output[len("JSON_LOG:"):]
        log_obj = json.loads(json_part)

        required_keys = [
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key"
        ]
        for key in required_keys:
            self.assertIn(key, log_obj, f"Missing required telemetry key: {key}")

        self.assertEqual(log_obj["correlation_id"], "test-corr-123")
        self.assertEqual(log_obj["chain_name"], "dna_batch_parser")
        self.assertEqual(log_obj["step"], "test_step")
        self.assertEqual(log_obj["outcome"], "success")
        self.assertEqual(log_obj["latency_ms"], 12.35)
        self.assertEqual(log_obj["actor_id"], "test_actor")
        self.assertEqual(log_obj["idempotency_key"], "VOL100")

if __name__ == '__main__':
    unittest.main()

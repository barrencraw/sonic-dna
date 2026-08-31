import inspect
import json
import os
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    run_batch,
    log_structured,
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_dna_sequence(self):
        """Assert canonical parameter name `dna_sequence` in DNACalculator.parse."""
        sig = inspect.signature(DNACalculator.parse)
        params = list(sig.parameters.keys())
        self.assertIn("dna_sequence", params)
        self.assertNotIn("dna_string", params)

    def test_typed_error_classification(self):
        """Assert exception taxonomy inherits properly from DNAProcessingError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_dna_status_enum_values(self):
        """Assert canonical terminal status strings."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")

    def test_structured_logging_keys(self):
        """Assert structured logs emit mandatory keys with expected schema."""
        captured_output = StringIO()
        with patch("sys.stdout", new=captured_output):
            log_structured(
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                correlation_id="test-corr-id",
                actor_id="test_actor",
                idempotency_key="VOL123"
            )

        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        data = json.loads(json_str)

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
            self.assertIn(key, data, f"Missing required telemetry key: {key}")

        self.assertEqual(data["correlation_id"], "test-corr-id")
        self.assertEqual(data["chain_name"], "test_chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["latency_ms"], 12.34)
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["idempotency_key"], "VOL123")

    def test_run_batch_telemetry_emission(self):
        """Assert batch processing emits JSON_LOG records during execution."""
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
                f.write("VOL08900750712\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                        "fade_in": {"description": "fade in duration", "min": 0, "max": 999, "pad": 3},
                        "fade_out": {"description": "fade out duration", "min": 0, "max": 999, "pad": 3},
                        "curve": {"description": "curve type", "min": 0, "max": 9, "pad": 1}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                captured = StringIO()
                with patch("sys.stdout", new=captured):
                    run_batch(correlation_id="batch-test-123")

                logs = [
                    json.loads(line[len("JSON_LOG: "):])
                    for line in captured.getvalue().splitlines()
                    if line.startswith("JSON_LOG: ")
                ]
                self.assertGreater(len(logs), 0)
                corr_ids = {l["correlation_id"] for l in logs}
                self.assertIn("batch-test-123", corr_ids)
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

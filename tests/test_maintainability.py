import io
import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    ThermalOverloadError,
    log_structured,
    run_batch
)
from utils.dna_calculator import DNACalculator

class TestMaintainability(unittest.TestCase):
    def test_dna_status_enum_values(self):
        """Verify DNAStatus lowercase values for contract compatibility."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy(self):
        """Verify typed exception classification hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(ThermalOverloadError, DNAProcessingError))

    def test_structured_logging_keys(self):
        """Verify log_structured emits standard fields."""
        stdout_capture = io.StringIO()
        with patch('sys.stdout', new=stdout_capture):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="dna_batch_parser",
                step="parse_sequence",
                outcome=DNAStatus.SUCCESS,
                latency_ms=15,
                actor_id="test_actor",
                idempotency_key="V100"
            )

        output = stdout_capture.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        log_obj = json.loads(json_str)

        required_keys = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key"
        }
        for key in required_keys:
            self.assertIn(key, log_obj, f"Missing required log key: {key}")

        self.assertEqual(log_obj["correlation_id"], "test-corr-123")
        self.assertEqual(log_obj["outcome"], "success")

    def test_canonical_naming_and_output_compat(self):
        """Verify DNACalculator.parse accepts dna_sequence and output contains canonical keys."""
        test_dir = tempfile.mkdtemp()
        try:
            data_dir = os.path.join(test_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
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

            calc = DNACalculator(rules_folder=rules_dir)
            parsed = calc.parse(dna_sequence="V100")
            self.assertEqual(parsed['rule'], 'Volume')

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch(correlation_id="test-run")
                json_out = os.path.join(output_dir, 'toSequence_parsed.json')
                with open(json_out, 'r') as f:
                    out_data = json.load(f)
                self.assertEqual(len(out_data), 1)
                self.assertIn('dna', out_data[0])
                self.assertIn('dna_sequence', out_data[0])
                self.assertEqual(out_data[0]['dna_sequence'], 'V100')
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

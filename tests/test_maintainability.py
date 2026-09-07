import sys
from unittest.mock import MagicMock

# Mock GUI / heavy dependencies if needed
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6

import unittest
import json
import os
import io
import tempfile
import shutil
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
    log_structured,
    run_batch
)
from utils.dna_calculator import DNACalculator, Rule

class TestMaintainability(unittest.TestCase):
    def test_dnastatus_enum_values_are_lowercase(self):
        """Verify DNAStatus values strictly use lowercase strings for backward compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_schema(self):
        """Verify log_structured outputs valid JSON containing all mandatory trace fields."""
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            entry = log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                correlation_id="test-cid-123",
                actor_id="test_actor",
                chain_name="test_chain",
                idempotency_key="VOL001",
                outcome_detail="test detail"
            )
            stdout_str = mock_stdout.getvalue().strip()
            self.assertTrue(stdout_str.startswith("JSON_LOG: "))
            json_part = stdout_str[len("JSON_LOG: "):]
            parsed = json.loads(json_part)

            mandatory_keys = {
                "timestamp",
                "correlation_id",
                "actor_id",
                "chain_name",
                "step",
                "outcome",
                "latency_ms",
                "idempotency_key",
                "outcome_detail"
            }
            self.assertEqual(set(parsed.keys()), mandatory_keys)
            self.assertEqual(parsed["correlation_id"], "test-cid-123")
            self.assertEqual(parsed["actor_id"], "test_actor")
            self.assertEqual(parsed["chain_name"], "test_chain")
            self.assertEqual(parsed["step"], "test_step")
            self.assertEqual(parsed["outcome"], "success")
            self.assertEqual(parsed["latency_ms"], 12.34)
            self.assertEqual(parsed["idempotency_key"], "VOL001")
            self.assertEqual(parsed["outcome_detail"], "test detail")

    def test_exception_taxonomy(self):
        """Verify exception hierarchy inheritance for typed error handling."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_canonical_naming_parameter_support(self):
        """Verify DNACalculator and Rule accept dna_sequence parameter."""
        test_dir = tempfile.mkdtemp()
        try:
            rule_file = os.path.join(test_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            rule = Rule(rule_file)
            res1 = rule.parse(dna_sequence="V100")
            self.assertEqual(res1, {"level": 100})

            calc = DNACalculator(rules_folder=test_dir)
            res2 = calc.parse(dna_sequence="V100")
            self.assertEqual(res2["rule"], "Volume")
            self.assertEqual(res2["values"], {"level": 100})
        finally:
            shutil.rmtree(test_dir)

    def test_backward_compatibility_output_keys(self):
        """Verify parsing batch produces outputs containing both 'dna' and 'dna_sequence' keys."""
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            raw_dir = os.path.join(test_dir, 'data', 'raw')
            output_dir = os.path.join(test_dir, 'data', 'output')
            rules_dir = os.path.join(test_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            with open(os.path.join(raw_dir, 'toSequence.txt'), 'w') as f:
                f.write("V100\n")

            with open(os.path.join(rules_dir, 'rules_Volume.json'), 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            os.chdir(test_dir)
            run_batch(correlation_id="test-compat-cid")

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out, 'r') as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            self.assertIn('dna', data[0])
            self.assertIn('dna_sequence', data[0])
            self.assertEqual(data[0]['dna'], 'V100')
            self.assertEqual(data[0]['dna_sequence'], 'V100')
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

import sys
from unittest.mock import MagicMock

# Mock GUI dependencies if needed before importing UI/PySide6
mock_pyside6 = MagicMock()
sys.modules.setdefault("PySide6", mock_pyside6)
sys.modules.setdefault("PySide6.QtWidgets", mock_pyside6)
sys.modules.setdefault("PySide6.QtCore", mock_pyside6)
sys.modules.setdefault("PySide6.QtGui", mock_pyside6)

import unittest
import os
import json
import io
import shutil
import tempfile
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    PersistenceError,
    RuleLoadError,
    InputReadError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    run_batch,
    load_ledger
)
from utils.dna_calculator import DNACalculator

class TestMaintainabilityAndRegressionGuard(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # VOL + 4 fields * pad 3 = VOL089007507123
        self.valid_dna = "VOL089007507123"

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write(f"{self.valid_dna}\n")

        # Mock Volume rule
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "master": {"description": "master level", "min": 0, "max": 999, "pad": 3},
                    "bus": {"description": "bus level", "min": 0, "max": 999, "pad": 3},
                    "aux": {"description": "aux level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "pan level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dnastatus_enum_values(self):
        """Verify DNAStatus uses canonical lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy(self):
        """Verify exception hierarchy and typing."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_corrupt_ledger_raises_ledger_load_error(self):
        """Verify corrupted JSON ledger raises typed LedgerLoadError."""
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'w') as f:
            f.write("INVALID JSON {{{")

        with self.assertRaises(LedgerLoadError):
            load_ledger(ledger_path)

    def test_canonical_naming_and_structured_logs(self):
        """Verify canonical key presence in output DTO and structured log fields."""
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        try:
            run_batch(correlation_id="test-corr-123", actor_id="test-runner")
        finally:
            sys.stdout = old_stdout

        # Verify output DTO keys
        json_out_path = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out_path))

        with open(json_out_path, 'r') as f:
            parsed = json.load(f)

        self.assertEqual(len(parsed), 1)
        entry = parsed[0]
        self.assertIn('dna_sequence', entry, "Canonical 'dna_sequence' key must be present in parsed DTO")
        self.assertIn('dna', entry, "Legacy 'dna' key must be present for backward compatibility")
        self.assertEqual(entry['dna_sequence'], self.valid_dna)

        # Verify structured telemetry log lines
        stdout_str = captured_output.getvalue()
        log_lines = [line for line in stdout_str.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(log_lines), 0, "Structured telemetry log entries should be emitted")

        required_keys = {
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

        for line in log_lines:
            json_str = line.replace("JSON_LOG:", "")
            payload = json.loads(json_str)
            for k in required_keys:
                self.assertIn(k, payload, f"Mandatory log field '{k}' missing from log entry: {payload}")
            self.assertEqual(payload["correlation_id"], "test-corr-123")
            self.assertEqual(payload["actor_id"], "test-runner")

    def test_calculator_parse_parameter_naming(self):
        """Verify DNACalculator.parse accepts dna_sequence argument."""
        calculator = DNACalculator(rules_folder=self.rules_dir)
        res = calculator.parse(dna_sequence=self.valid_dna)
        self.assertEqual(res['rule'], "Volume")

if __name__ == '__main__':
    unittest.main()

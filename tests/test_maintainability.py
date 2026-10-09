import sys
from unittest.mock import MagicMock

# Mock GUI/native dependencies prior to imports if not installed
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import inspect
import io

from utils.dna_calculator import DNACalculator
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
    def test_naming_alignment_signature(self):
        """Verify parameter signature alignment on DNACalculator.parse uses dna_sequence."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", sig.parameters)

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum members have lowercase string values for compatibility."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_typed_exception_taxonomy(self):
        """Verify explicit typed exception hierarchy inheritance."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_formatting_and_keys(self):
        """Verify structured logging emits valid JSON prefixed with JSON_LOG: containing mandatory keys."""
        captured_output = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test_actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=42,
                idempotency_key="test_key",
                outcome_detail="test_detail"
            )
        finally:
            sys.stdout = original_stdout

        output_str = captured_output.getvalue().strip()
        self.assertTrue(output_str.startswith("JSON_LOG:"))

        json_part = output_str[len("JSON_LOG:"):]
        log_data = json.loads(json_part)

        mandatory_keys = [
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
        for key in mandatory_keys:
            self.assertIn(key, log_data)

        self.assertEqual(log_data["correlation_id"], "test-corr-123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["outcome"], "success")

    def test_backward_compatibility_output_keys(self):
        """Verify output JSON contains both legacy 'dna' and canonical 'dna_sequence' keys."""
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
                f.write("VOL100\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
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
                run_batch(correlation_id="test-batch", actor_id="test_runner")
                json_out = os.path.join(output_dir, 'toSequence_parsed.json')
                self.assertTrue(os.path.exists(json_out))

                with open(json_out, 'r') as f:
                    records = json.load(f)
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    self.assertIn('dna', record)
                    self.assertIn('dna_sequence', record)
                    self.assertEqual(record['dna'], 'VOL100')
                    self.assertEqual(record['dna_sequence'], 'VOL100')
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

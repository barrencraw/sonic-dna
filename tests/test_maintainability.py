import sys
from unittest.mock import MagicMock

# Mock dependencies before imports if needed
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
from unittest.mock import patch
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    AtomicWriteError,
    LedgerSaveError,
    log_structured,
    run_batch
)

class TestMaintainability(unittest.TestCase):
    def test_naming_alignment_dna_sequence(self):
        """Verify that DNACalculator.parse and Rule.parse use dna_sequence parameter name."""
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters)

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters)

    def test_dna_status_enum_lowercase(self):
        """Verify that DNAStatus contains expected lowercase string values."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy(self):
        """Verify typed error hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))

    def test_structured_logging_fields(self):
        """Verify structured log format contains all required observability keys."""
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            log_structured(
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=10,
                correlation_id="test-corr-id",
                actor_id="test-actor",
                idempotency_key="VOL001",
                outcome_detail="test detail"
            )
        output = captured_output.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        payload = json.loads(json_str)

        required_keys = [
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        ]
        for key in required_keys:
            self.assertIn(key, payload)
        self.assertEqual(payload["correlation_id"], "test-corr-id")
        self.assertEqual(payload["actor_id"], "test-actor")
        self.assertEqual(payload["step"], "test_step")
        self.assertEqual(payload["outcome"], "success")

    def test_backwards_compatible_output_keys(self):
        """Verify that batch processing outputs contain both legacy 'dna' and canonical 'dna_sequence' keys."""
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(test_dir)
            data_dir = os.path.join(test_dir, 'data')
            raw_dir = os.path.join(data_dir, 'raw')
            output_dir = os.path.join(data_dir, 'output')
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

            result = run_batch()
            self.assertEqual(result['status'], DNAStatus.SUCCESS)

            json_out_path = os.path.join(output_dir, 'toSequence_parsed.json')
            with open(json_out_path, 'r') as f:
                parsed_list = json.load(f)

            self.assertEqual(len(parsed_list), 1)
            entry = parsed_list[0]
            self.assertIn('dna', entry)
            self.assertIn('dna_sequence', entry)
            self.assertEqual(entry['dna'], 'V100')
            self.assertEqual(entry['dna_sequence'], 'V100')

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

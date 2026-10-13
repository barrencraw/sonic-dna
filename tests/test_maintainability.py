import sys
from unittest.mock import MagicMock

# Mock GUI and audio dependencies before imports
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
import json
import shutil
import tempfile
import io
import inspect
from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError
)


class TestMaintainability(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL08900750712\n")

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "pan level", "min": 0, "max": 999, "pad": 3},
                    "mute": {"description": "mute flag", "min": 0, "max": 9, "pad": 1},
                    "solo": {"description": "solo flag", "min": 0, "max": 9, "pad": 1}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_status_enum_lowercase(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy(self):
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_naming_alignment_dna_sequence_parameter(self):
        calc_sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', calc_sig.parameters, "DNACalculator.parse must use parameter name 'dna_sequence'")

        rule_sig = inspect.signature(Rule.parse)
        self.assertIn('dna_sequence', rule_sig.parameters, "Rule.parse must use parameter name 'dna_sequence'")

    def test_output_fields_contain_legacy_and_canonical_keys(self):
        run_batch(correlation_id="test-corr-123")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            item = data[0]
            self.assertIn('dna', item, "Output JSON record must contain legacy 'dna' key")
            self.assertIn('dna_sequence', item, "Output JSON record must contain canonical 'dna_sequence' key")
            self.assertEqual(item['dna'], item['dna_sequence'])

    def test_structured_logging_fields(self):
        captured_output = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = captured_output
            run_batch(correlation_id="test-log-456")
        finally:
            sys.stdout = original_stdout

        log_lines = [line for line in captured_output.getvalue().splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(log_lines), 0, "Structured logs prefixed with JSON_LOG: should be emitted")

        required_fields = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"
        }

        for line in log_lines:
            json_str = line[len("JSON_LOG:"):].strip()
            payload = json.loads(json_str)
            for field in required_fields:
                self.assertIn(field, payload, f"Structured log missing required field '{field}'")
            self.assertEqual(payload["correlation_id"], "test-log-456")
            self.assertEqual(payload["chain_name"], "dna_batch_parser")


if __name__ == '__main__':
    unittest.main()

import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Mock GUI and audio dependencies prior to imports
mock_sys = MagicMock()
sys.modules["PySide6"] = mock_sys
sys.modules["PySide6.QtWidgets"] = mock_sys
sys.modules["PySide6.QtCore"] = mock_sys
sys.modules["PySide6.QtGui"] = mock_sys
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    log_structured
)
from utils.dna_calculator import DNACalculator

class TestMaintainabilityAndObservability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a valid rule file for Volume ('V')
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\n")

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_status_enum_values(self):
        """Ensure terminal outcome statuses are explicitly standardized and lowercase."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_typed_exception_hierarchy(self):
        """Ensure all domain/processing exceptions derive from DNAProcessingError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))

    def test_structured_logging_keys(self):
        """Verify structured JSON logs output all required observability fields."""
        captured_logs = []

        def mock_print(msg, *args, **kwargs):
            if isinstance(msg, str) and msg.startswith("JSON_LOG:"):
                json_str = msg.replace("JSON_LOG:", "").strip()
                captured_logs.append(json.loads(json_str))

        with patch("builtins.print", side_effect=mock_print):
            run_batch(correlation_id="test-corr-1234", actor_id="test_runner")

        self.assertGreater(len(captured_logs), 0)
        required_fields = {
            "timestamp", "correlation_id", "chain_name", "step",
            "outcome", "latency_ms", "actor_id", "idempotency_key", "outcome_detail"
        }

        for log_entry in captured_logs:
            self.assertEqual(set(log_entry.keys()), required_fields)
            self.assertEqual(log_entry["correlation_id"], "test-corr-1234")
            self.assertEqual(log_entry["chain_name"], "dna_batch_parser")
            self.assertEqual(log_entry["actor_id"], "test_runner")

    def test_canonical_and_legacy_key_alignment(self):
        """Ensure output JSON contains both 'dna_sequence' (canonical) and 'dna' (legacy)."""
        run_batch(correlation_id="test-corr-key-alignment")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r', encoding='utf-8') as f:
            parsed = json.load(f)

        self.assertEqual(len(parsed), 1)
        self.assertIn('dna_sequence', parsed[0])
        self.assertIn('dna', parsed[0])
        self.assertEqual(parsed[0]['dna_sequence'], "V100")
        self.assertEqual(parsed[0]['dna'], "V100")

if __name__ == '__main__':
    unittest.main()

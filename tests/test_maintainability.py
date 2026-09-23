import sys
from unittest.mock import MagicMock

# Mock non-installed heavy packages before imports if running without native deps
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
mock_scipy = MagicMock()
sys.modules["scipy"] = mock_scipy
sys.modules["scipy.io"] = mock_scipy.io
sys.modules["scipy.io.wavfile"] = mock_scipy.io.wavfile

import os
import json
import tempfile
import shutil
import unittest
from io import StringIO
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError
)
from utils.dna_calculator import DNACalculator

class TestMaintainabilityGuard(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "curve": {"description": "curve type", "min": 0, "max": 999, "pad": 3},
                    "smoothing": {"description": "smoothing value", "min": 0, "max": 999, "pad": 3},
                    "headroom": {"description": "headroom pad", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_status_enum_values(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_exception_taxonomy_hierarchy(self):
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_canonical_naming_keys_in_output(self):
        run_batch(correlation_id="test_corr_001", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            entry = data[0]
            # Verify canonical naming 'dna_sequence' and backward-compatible 'dna'
            self.assertIn('dna_sequence', entry)
            self.assertIn('dna', entry)
            self.assertEqual(entry['dna_sequence'], "VOL08900750712")
            self.assertEqual(entry['dna'], "VOL08900750712")

    def test_structured_log_field_presence(self):
        with patch('sys.stdout', new=StringIO()) as fake_out:
            run_batch(correlation_id="trace_xyz", actor_id="maintainability_test")
            output = fake_out.getvalue()

        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]
        self.assertGreater(len(log_lines), 0, "Structured JSON log lines should be emitted")

        required_fields = {
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
            json_str = line.replace("JSON_LOG: ", "")
            parsed = json.loads(json_str)
            self.assertEqual(set(parsed.keys()), required_fields)
            self.assertEqual(parsed["chain_name"], "dna_batch_parsing")

        init_log = json.loads(log_lines[0].replace("JSON_LOG: ", ""))
        self.assertEqual(init_log["correlation_id"], "trace_xyz")
        self.assertEqual(init_log["actor_id"], "maintainability_test")

if __name__ == '__main__':
    unittest.main()

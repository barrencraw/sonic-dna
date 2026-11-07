import sys
from unittest.mock import MagicMock

# Mock GUI and native C dependencies if unavailable
mock_pyside6 = MagicMock()
sys.modules.setdefault("PySide6", mock_pyside6)
sys.modules.setdefault("PySide6.QtWidgets", mock_pyside6)
sys.modules.setdefault("PySide6.QtCore", mock_pyside6)
sys.modules.setdefault("PySide6.QtGui", mock_pyside6)

import unittest
import os
import shutil
import tempfile
import json
import io
from contextlib import redirect_stdout

from utils.dna_ui import (
    run_batch,
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    PersistenceError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured
)

class TestMaintainability(unittest.TestCase):

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
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_and_backward_compatibility(self):
        """Verify DTO contains both canonical 'dna_sequence' and backward-compatible 'dna' keys."""
        run_batch(correlation_id="test_naming")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            entry = data[0]
            self.assertIn("dna_sequence", entry, "Canonical naming 'dna_sequence' missing from DTO")
            self.assertIn("dna", entry, "Legacy naming 'dna' missing from DTO")
            self.assertEqual(entry["dna_sequence"], "VOL08900750712")
            self.assertEqual(entry["dna"], "VOL08900750712")

    def test_exception_taxonomy(self):
        """Verify that typed exceptions inherit from DNAProcessingError / PersistenceError."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_schema(self):
        """Verify that structured logs follow mandatory schema key requirements."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured("test_step", DNAStatus.SUCCESS.value, correlation_id="c123", actor_id="test_actor", latency_ms=12.34, idempotency_key="key1", outcome_detail="detail1")

        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        log_json_str = output[len("JSON_LOG: "):]
        log_data = json.loads(log_json_str)

        required_keys = ["timestamp", "correlation_id", "actor_id", "chain_name", "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"]
        for key in required_keys:
            self.assertIn(key, log_data, f"Mandatory log key '{key}' missing from structured log")

        self.assertEqual(log_data["correlation_id"], "c123")
        self.assertEqual(log_data["actor_id"], "test_actor")
        self.assertEqual(log_data["chain_name"], "dna_batch_parser")
        self.assertEqual(log_data["step"], "test_step")
        self.assertEqual(log_data["outcome"], "success")
        self.assertEqual(log_data["latency_ms"], 12.34)
        self.assertEqual(log_data["idempotency_key"], "key1")
        self.assertEqual(log_data["outcome_detail"], "detail1")

if __name__ == '__main__':
    unittest.main()

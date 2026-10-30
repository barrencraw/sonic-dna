import io
import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Mock GUI dependencies if needed for test discovery
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

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
from utils.dna_calculator import DNACalculator, RuleParseError


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
                    "peak": {"description": "peak", "min": 0, "max": 99, "pad": 3},
                    "rms": {"description": "rms", "min": 0, "max": 99, "pad": 3},
                    "lufs": {"description": "lufs", "min": 0, "max": 99, "pad": 3},
                    "crest": {"description": "crest", "min": 0, "max": 99, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dna_status_enum_lowercase_values(self):
        """Verify DNAStatus enum uses exact lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed exception classification hierarchy."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_naming_alignment_in_outputs(self):
        """Verify output JSON contains canonical key 'dna_sequence' alongside legacy 'dna'."""
        run_batch(correlation_id="test-corr-123", actor_id="test_actor")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))

        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertIn("dna_sequence", entry)
        self.assertIn("dna", entry)
        self.assertEqual(entry["dna_sequence"], "VOL08900750712")
        self.assertEqual(entry["dna"], "VOL08900750712")

    def test_structured_logging_schema(self):
        """Verify structured logs contain mandatory fields and valid JSON formatting."""
        captured_output = io.StringIO()
        with patch("sys.stdout", captured_output):
            run_batch(correlation_id="trace-abc-123", actor_id="maintainability_test")

        output_text = captured_output.getvalue()
        json_log_lines = [
            line[len("JSON_LOG:"):] for line in output_text.splitlines()
            if line.startswith("JSON_LOG:")
        ]

        self.assertGreater(len(json_log_lines), 0, "Should have emitted at least one structured log line")

        mandatory_fields = {
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

        for log_str in json_log_lines:
            log_obj = json.loads(log_str)
            self.assertTrue(mandatory_fields.issubset(log_obj.keys()), f"Missing log fields in: {log_obj}")
            self.assertEqual(log_obj["correlation_id"], "trace-abc-123")
            self.assertEqual(log_obj["actor_id"], "maintainability_test")
            self.assertEqual(log_obj["chain_name"], "dna_batch_parsing")


if __name__ == "__main__":
    unittest.main()

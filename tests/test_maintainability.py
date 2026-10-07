import sys
from unittest.mock import MagicMock

# Mock GUI dependencies if needed
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import os
import json
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from utils.dna_ui import (
    DNAStatus,
    DNAProcessingError,
    RuleLoadError,
    InputReadError,
    ThermalOverloadError,
    PersistenceError,
    LedgerLoadError,
    LedgerSaveError,
    AtomicWriteError,
    log_structured,
    run_batch
)

class TestMaintainabilityRegressionGuard(unittest.TestCase):

    def test_dna_status_lowercase_properties(self):
        """Verify DNAStatus properties and values are strictly lowercase strings."""
        status = DNAStatus()
        self.assertEqual(status.success, "success")
        self.assertEqual(status.error, "error")
        self.assertEqual(status.skipped, "skipped")
        self.assertEqual(status.refused, "refused")
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_exception_taxonomy_hierarchy(self):
        """Verify typed exception taxonomy subclass relationships."""
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(ThermalOverloadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerLoadError, PersistenceError))
        self.assertTrue(issubclass(LedgerSaveError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))

    def test_structured_log_schema_presence(self):
        """Verify structured log output format and mandatory schema fields."""
        stdout_capture = StringIO()
        with patch('sys.stdout', stdout_capture):
            log_structured(
                correlation_id="test-corr-123",
                actor_id="test_actor",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=12.34,
                idempotency_key="key-999",
                outcome_detail="test detail"
            )

        output = stdout_capture.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))
        json_str = output[len("JSON_LOG: "):]
        log_dict = json.loads(json_str)

        required_keys = [
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
        for key in required_keys:
            self.assertIn(key, log_dict)

        self.assertEqual(log_dict["correlation_id"], "test-corr-123")
        self.assertEqual(log_dict["actor_id"], "test_actor")
        self.assertEqual(log_dict["chain_name"], "test_chain")
        self.assertEqual(log_dict["step"], "test_step")
        self.assertEqual(log_dict["outcome"], "success")

    def test_backward_compatible_output_keys(self):
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
                f.write("VOL08900750712\n")

            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "master": {"description": "master volume", "min": 0, "max": 999, "pad": 3},
                        "bus_a": {"description": "bus a volume", "min": 0, "max": 999, "pad": 3},
                        "bus_b": {"description": "bus b volume", "min": 0, "max": 999, "pad": 3},
                        "headroom": {"description": "headroom", "min": 0, "max": 99, "pad": 2}
                    }
                }, f)

            old_cwd = os.getcwd()
            os.chdir(test_dir)
            try:
                run_batch()
            finally:
                os.chdir(old_cwd)

            json_out = os.path.join(output_dir, 'toSequence_parsed.json')
            self.assertTrue(os.path.exists(json_out))
            with open(json_out, 'r') as f:
                records = json.load(f)
            self.assertEqual(len(records), 1)
            self.assertIn('dna', records[0])
            self.assertIn('dna_sequence', records[0])
            self.assertEqual(records[0]['dna'], "VOL08900750712")
            self.assertEqual(records[0]['dna_sequence'], "VOL08900750712")
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

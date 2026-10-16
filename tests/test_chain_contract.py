import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports
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
import io
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError

class TestChainContract(unittest.TestCase):
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
        self.dna_seq = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{self.dna_seq}\n")

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

    def test_happy_path_and_telemetry(self):
        """Verify happy path processing and structured JSON telemetry emission."""
        stdout_capture = io.StringIO()
        with patch('sys.stdout', stdout_capture):
            run_batch(correlation_id="test-corr-123", actor_id="test_actor")

        output_text = stdout_capture.getvalue()
        json_logs = [
            json.loads(line.replace("JSON_LOG: ", ""))
            for line in output_text.splitlines()
            if line.startswith("JSON_LOG:")
        ]

        self.assertTrue(len(json_logs) >= 3)
        start_log = json_logs[0]
        self.assertEqual(start_log["correlation_id"], "test-corr-123")
        self.assertEqual(start_log["actor_id"], "test_actor")
        self.assertEqual(start_log["chain_name"], "dna_batch_parser")
        self.assertEqual(start_log["step"], "start")

        parse_log = [l for l in json_logs if l["step"] == "parse_sequence"][0]
        self.assertEqual(parse_log["idempotency_key"], self.dna_seq)
        self.assertEqual(parse_log["outcome"], "success")

        end_log = json_logs[-1]
        self.assertEqual(end_log["step"], "end")
        self.assertEqual(end_log["outcome"], "success")

    def test_idempotency_double_invocation(self):
        """Verify that invoking the batch parser twice on the same key skips re-processing."""
        run_batch(correlation_id="corr-1")

        stdout_capture = io.StringIO()
        with patch('sys.stdout', stdout_capture):
            run_batch(correlation_id="corr-2")

        output_text = stdout_capture.getvalue()
        json_logs = [
            json.loads(line.replace("JSON_LOG: ", ""))
            for line in output_text.splitlines()
            if line.startswith("JSON_LOG:")
        ]

        dedupe_logs = [l for l in json_logs if l["step"] == "dedupe"]
        self.assertEqual(len(dedupe_logs), 1)
        self.assertEqual(dedupe_logs[0]["outcome"], "skipped")
        self.assertEqual(dedupe_logs[0]["idempotency_key"], self.dna_seq)

    def test_persistence_failure_raises_persistence_error(self):
        """Verify atomicity: failure during write raises PersistenceError and logs error."""
        stdout_capture = io.StringIO()
        with patch('json.dump', side_effect=IOError("Disk write failed")):
            with patch('sys.stdout', stdout_capture):
                with self.assertRaises(PersistenceError):
                    run_batch(correlation_id="corr-err")

        output_text = stdout_capture.getvalue()
        json_logs = [
            json.loads(line.replace("JSON_LOG: ", ""))
            for line in output_text.splitlines()
            if line.startswith("JSON_LOG:")
        ]

        err_logs = [l for l in json_logs if l["outcome"] == "error"]
        self.assertTrue(len(err_logs) > 0)
        self.assertEqual(err_logs[0]["step"], "persist_outputs")

if __name__ == '__main__':
    unittest.main()

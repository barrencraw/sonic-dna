import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()
sys.modules["watchdog"] = MagicMock()
sys.modules["watchdog.observers"] = MagicMock()
sys.modules["watchdog.events"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestTelemetry(unittest.TestCase):
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
            f.write("V100\n")

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_structured_logs_emitted(self):
        """Verify that JSON_LOG: lines are printed during execution."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]

        self.assertTrue(len(log_lines) >= 3, f"Expected at least 3 log lines, got {len(log_lines)}")

        # Parse logs
        logs = [json.loads(line[9:]) for line in log_lines]

        # Check start log
        start_log = next(l for l in logs if l['step'] == 'batch_start')
        self.assertEqual(start_log['correlation_id'], 'test-corr-id')
        self.assertEqual(start_log['actor_id'], 'test-actor')

        # Check item log
        item_log = next(l for l in logs if l['step'] == 'item_process')
        self.assertEqual(item_log['outcome'], 'success')
        self.assertEqual(item_log['idempotency_key'], 'V100')
        self.assertIn('latency_ms', item_log)

        # Check end log
        end_log = next(l for l in logs if l['step'] == 'batch_end')
        self.assertEqual(end_log['outcome'], 'success')
        self.assertEqual(end_log['processed_count'], 1)

if __name__ == '__main__':
    unittest.main()

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
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import json
import shutil
import tempfile
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a rule file
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

    def test_observability_logs(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        dna = "VOL123"
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(log_lines) >= 3, f"Expected at least 3 logs, got {len(log_lines)}")

        logs = [json.loads(line.replace('[OBSERVABILITY] ', '')) for line in log_lines]

        # Check start log
        self.assertEqual(logs[0]['step'], 'start')
        self.assertEqual(logs[0]['outcome'], 'STARTED')
        self.assertEqual(logs[0]['correlation_id'], 'test-corr-id')
        self.assertEqual(logs[0]['actor_id'], 'test-actor')

        # Check process_dna log
        process_logs = [l for l in logs if l['step'] == 'process_dna']
        self.assertEqual(len(process_logs), 1)
        self.assertEqual(process_logs[0]['outcome'], 'SUCCESS')
        self.assertEqual(process_logs[0]['idempotency_key'], dna)
        self.assertIn('latency_ms', process_logs[0])

        # Check complete log
        self.assertEqual(logs[-1]['step'], 'complete')
        self.assertEqual(logs[-1]['outcome'], 'SUCCESS')

    def test_dedupe_log(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        dna = "VOL123"
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        # First run to populate ledger
        run_batch(correlation_id="corr-1", actor_id="actor-1")

        # Second run with same DNA
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="corr-2", actor_id="actor-2")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]
        logs = [json.loads(line.replace('[OBSERVABILITY] ', '')) for line in log_lines]

        process_logs = [l for l in logs if l['step'] == 'process_dna']
        self.assertEqual(len(process_logs), 1)
        self.assertEqual(process_logs[0]['outcome'], 'DEDUPE')
        self.assertEqual(process_logs[0]['idempotency_key'], dna)

if __name__ == '__main__':
    unittest.main()

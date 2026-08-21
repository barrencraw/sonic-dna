import sys
from unittest.mock import MagicMock

sys.modules.setdefault("PySide6", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("PySide6.QtCore", MagicMock())
sys.modules.setdefault("PySide6.QtGui", MagicMock())

import unittest
import os
import shutil
import tempfile
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        actual_rules = os.path.join(self.old_cwd, 'rules')
        if os.path.exists(actual_rules):
            shutil.copytree(actual_rules, self.rules_dir, dirs_exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_dnastatus_lowercase_values(self):
        self.assertEqual(DNAStatus.SUCCESS, "success")
        self.assertEqual(DNAStatus.ERROR, "error")
        self.assertEqual(DNAStatus.SKIPPED, "skipped")
        self.assertEqual(DNAStatus.REFUSED, "refused")

    def test_structured_telemetry_schema(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        f_out = io.StringIO()
        with redirect_stdout(f_out):
            run_batch(correlation_id="test-correlation-123")

        output = f_out.getvalue()
        json_log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertGreater(len(json_log_lines), 0, "Telemetry stdout must emit JSON_LOG: lines")

        payload = json.loads(json_log_lines[0].replace("JSON_LOG:", ""))
        mandatory_fields = [
            'timestamp',
            'correlation_id',
            'actor_id',
            'chain_name',
            'step',
            'outcome',
            'latency_ms',
            'idempotency_key',
            'outcome_detail'
        ]
        for field in mandatory_fields:
            self.assertIn(field, payload, f"Missing mandatory telemetry field '{field}'")

        self.assertEqual(payload['correlation_id'], "test-correlation-123")
        self.assertEqual(payload['actor_id'], "batch_parser")
        self.assertEqual(payload['chain_name'], "dna_batch_parser")
        self.assertEqual(payload['idempotency_key'], dna)
        self.assertEqual(payload['outcome'], "success")

    def test_backward_compatibility_keys(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            entry = data[0]
            self.assertIn('dna', entry)
            self.assertIn('dna_sequence', entry)
            self.assertEqual(entry['dna'], dna)
            self.assertEqual(entry['dna_sequence'], dna)

if __name__ == '__main__':
    unittest.main()

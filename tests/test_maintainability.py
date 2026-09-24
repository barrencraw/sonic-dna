import unittest
import os
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import utils.dna_ui as dna_ui
from utils.dna_ui import run_batch, DNAStatus, ThermalOverloadError

class MockDatetime:
    current_time = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_string):
        return datetime.strptime(date_string, format_string)

    @classmethod
    def advance_time(cls, seconds):
        cls.current_time += timedelta(seconds=seconds)

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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

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

    def test_dna_status_enum_values(self):
        """Verify DNAStatus enum canonical lowercase values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")

    def test_structured_logging_keys(self):
        """Verify that structured log contains required keys."""
        logs = []
        def mock_print(*args, **kwargs):
            msg = " ".join(map(str, args))
            if msg.startswith("JSON_LOG: "):
                logs.append(json.loads(msg[10:]))

        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        with patch('builtins.print', side_effect=mock_print):
            run_batch(correlation_id="test-corr-123", actor_id="test_actor")

        self.assertTrue(len(logs) >= 2)
        log = logs[0]
        required_keys = ["timestamp", "correlation_id", "actor_id", "chain_name", "step", "outcome", "latency_ms", "idempotency_key", "outcome_detail"]
        for key in required_keys:
            self.assertIn(key, log)
        self.assertEqual(log["correlation_id"], "test-corr-123")
        self.assertEqual(log["actor_id"], "test_actor")
        self.assertEqual(log["chain_name"], "dna_batch_parser")

    def test_backward_compatibility_keys_in_output(self):
        """Verify JSON & CSV outputs maintain both legacy 'dna' and canonical 'dna_sequence' keys."""
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn('dna', data[0])
        self.assertIn('dna_sequence', data[0])
        self.assertEqual(data[0]['dna'], 'VOL100')
        self.assertEqual(data[0]['dna_sequence'], 'VOL100')

if __name__ == '__main__':
    unittest.main()

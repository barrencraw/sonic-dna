import unittest
import os
import json
import shutil
import tempfile
import datetime
from unittest.mock import patch

from utils.dna_ui import run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE

class MockDatetime:
    timezone = datetime.timezone
    class datetime:
        _current_time = None
        @classmethod
        def now(cls, tz=None):
            return cls._current_time
        @classmethod
        def fromisoformat(cls, s):
            # Convert 'Z' suffix to '+00:00' to be compatible with older python versions if any
            if s.endswith('Z'):
                s = s[:-1] + '+00:00'
            return datetime.datetime.fromisoformat(s)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup temporary directories for sandbox execution
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Create mock rule file so the calculator works
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        # Pre-populate empty ledger
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Set default mock time
        MockDatetime.datetime._current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation(self):
        # 1. Prepare input sequence with 3 DNA items
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL010\nVOL020\nVOL030\n")

        # 2. Run batch parser
        run_batch()

        # 3. Read ledger and verify heat accumulated
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        expected_heat = 3 * HEAT_PER_SEQ # 60.0
        self.assertEqual(ledger.get("system_heat"), expected_heat)
        self.assertEqual(ledger.get("last_updated"), "2026-03-02T12:00:00Z")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_time_based_cooling(self):
        # 1. Pre-set heat in ledger to 60.0 at 12:00:00
        initial_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({
                "system_heat": 60.0,
                "last_updated": initial_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }, f)

        # 2. Advance clock by 10 seconds (cooling of 10 * 2.0 = 20.0)
        MockDatetime.datetime._current_time = initial_time + datetime.timedelta(seconds=10)

        # 3. Process an empty batch or 1 sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL040\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        # Heat should cool to 40.0, then add 20.0 for processing VOL040 -> 60.0
        self.assertEqual(ledger.get("system_heat"), 60.0)
        self.assertEqual(ledger.get("last_updated"), "2026-03-02T12:00:10Z")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_lockout_enforcement(self):
        # 1. Pre-set heat in ledger close to max (90.0)
        initial_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({
                "system_heat": 90.0,
                "last_updated": initial_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }, f)

        # 2. Run batch with a sequence (90 + 20 = 110 > 100)
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL050\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        # 3. Verify error messages and keys
        self.assertEqual(context.exception.reason, "Thermal Lockout")
        self.assertEqual(context.exception.consequence, "Heat Accumulation")
        self.assertEqual(context.exception.hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # 4. Verify that the sequence was NOT processed and is not in the ledger
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        self.assertNotIn("VOL050", ledger)
        # Heat and timestamp should still be updated in the ledger to show state at lockout attempt
        self.assertEqual(ledger.get("system_heat"), 90.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_prevents_heat_accumulation(self):
        # 1. Run a batch with same DNA sequence twice
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL010\nVOL010\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        # Should only accumulate heat once (20.0)
        self.assertEqual(ledger.get("system_heat"), 20.0)

if __name__ == '__main__':
    unittest.main()

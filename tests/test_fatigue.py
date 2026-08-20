import os
import json
import shutil
import tempfile
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError

class FakeDatetime(datetime.datetime):
    current_time = datetime.datetime(2025, 6, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_spec):
        dt = datetime.datetime.strptime(date_string, format_spec)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

class MockDatetimeModule:
    timezone = datetime.timezone
    datetime = FakeDatetime

class TestThermalFatigue(unittest.TestCase):
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

        # Create valid volume rule file
        rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        FakeDatetime.current_time = datetime.datetime(2025, 6, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_thermal_fatigue_idempotency_and_lockout(self):
        """
        Proof Test:
        1. Heat accumulates +2.0 per sequence parsed.
        2. Re-submitting an already processed sequence (idempotency) adds 0 heat.
        3. Reaching or exceeding threshold (10.0 heat) triggers ThermalOverloadError with exact UI message keys.
        4. No silent drains: refused batch retains remaining sequences.
        5. Time dissipation (0.5 heat/sec) reduces heat and restores system availability.
        """
        # Batch 1: 4 sequences -> 4 * 2.0 = 8.0 heat (below 10.0 lockout threshold)
        dna_list_1 = [
            "VOL001",
            "VOL002",
            "VOL003",
            "VOL004"
        ]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dna_list_1) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Re-submit duplicate sequence: idempotency check ensures 0 heat added
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL001\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        # Core heat must remain 8.0 because duplicate sequence was skipped
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Submit 2 new sequences -> VOL005 pushes heat to 10.0 -> lockout triggered on threshold!
        dna_list_2 = ["VOL005", "VOL006"]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dna_list_2) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

        err = ctx.exception
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check ledger state: core heat is now 10.0
        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # Verify no silent drains: VOL006 was not processed and input file retains content
        with open(self.input_file, 'r', encoding='utf-8') as f:
            remaining_content = f.read()
        self.assertIn("VOL006", remaining_content)

        # Advance time by 10 seconds: decay = 10 * 0.5 = 5.0 heat -> heat becomes 5.0
        FakeDatetime.current_time += datetime.timedelta(seconds=10)

        # Now VOL006 can be processed safely without hitting lockout
        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        # Heat started at 5.0, plus 2.0 for VOL006 = 7.0
        self.assertEqual(ledger_data['system_state']['core_heat'], 7.0)

if __name__ == '__main__':
    unittest.main()

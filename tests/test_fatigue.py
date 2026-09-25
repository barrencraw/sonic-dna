import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, ThermalOverloadError, UI_MESSAGES

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': '2026-03-02T10:00:00Z'}}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        """Verify that processing new DNA sequences accumulates heat (+2.0 per sequence)."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        fake_now = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now

        with patch('datetime.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 2.0)

    def test_thermal_dissipation(self):
        """Verify that elapsed time cools the core at 0.5 units/sec."""
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        t1 = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        class MockDatetime1(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t1

        with patch('datetime.datetime', MockDatetime1):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 2.0)

        # 2 seconds later -> -1.0 heat decay, +2.0 new heat = 3.0 core heat
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        t2 = datetime.datetime(2026, 3, 2, 10, 0, 2, tzinfo=datetime.timezone.utc)
        class MockDatetime2(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t2

        with patch('datetime.datetime', MockDatetime2):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 3.0)

    def test_thermal_lockout_enforcement(self):
        """Verify that reaching 10.0 heat triggers ThermalOverloadError with UI keys."""
        with open(self.ledger_path, 'w') as f:
            json.dump({
                'ledger': {},
                'system_state': {'core_heat': 10.0, 'last_processed_timestamp': '2026-03-02T10:00:00Z'}
            }, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        t1 = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t1

        with patch('datetime.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err_msg = str(cm.exception)
        self.assertIn(UI_MESSAGES["REFUSAL_REASON"], err_msg)
        self.assertIn(UI_MESSAGES["NEXT_ACTION_HINT"], err_msg)

    def test_no_silent_drains_on_deduplication(self):
        """Verify deduplicated sequences produce no heat accumulation (no silent drains)."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        t1 = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t1

        with patch('datetime.datetime', MockDatetime):
            run_batch() # Core heat = 2.0

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('datetime.datetime', MockDatetime):
            run_batch() # Re-run with same DNA at same timestamp -> heat should remain 2.0

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 2.0)

if __name__ == '__main__':
    unittest.main()

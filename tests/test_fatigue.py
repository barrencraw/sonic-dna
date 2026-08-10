import os
import json
import shutil
import unittest
import datetime
import tempfile
from unittest.mock import patch, MagicMock
from utils.dna_ui import run_batch, ThermalOverloadError, load_ledger, DNAStatus

_real_datetime = datetime.datetime

class MockDatetime:
    _mock_now = None

    @classmethod
    def set_now(cls, dt_str):
        cls._mock_now = _real_datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%SZ')

    @classmethod
    def now(cls, tz=None):
        return cls._mock_now

    @classmethod
    def strptime(cls, date_string, format_string):
        return _real_datetime.strptime(date_string, format_string)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Start with fresh empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}}, f)

        # Set initial mock time
        MockDatetime.set_now('2026-03-02T15:00:00Z')

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('datetime.datetime', MockDatetime)
    def test_heat_accumulation_on_success(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # First run: should succeed and core_heat should be 2.0
        res = run_batch()
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.processed_count, 1)

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 2.0)
        self.assertEqual(data['system_state']['last_processed_timestamp'], '2026-03-02T15:00:00Z')

        # Next run with a different DNA sequence
        MockDatetime.set_now('2026-03-02T15:00:01Z') # 1 second later (cools by 0.5, then adds 2.0 -> should be 2.0 - 0.5 + 2.0 = 3.5)
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        res2 = run_batch()
        self.assertEqual(res2.status, "SUCCESS")

        with open(self.ledger_path, 'r') as f:
            data2 = json.load(f)
        self.assertEqual(data2['system_state']['core_heat'], 3.5)

    @patch('datetime.datetime', MockDatetime)
    def test_idempotency_no_heat_accumulation(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Run 1: success, heat is 2.0
        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 2.0)

        # Run 2: deduplication, no heat should accumulate
        MockDatetime.set_now('2026-03-02T15:00:02Z') # cools by 1.0 -> heat should be 1.0. Deduplication means no additional heat.
        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 1.0) # cooled down, didn't add heat because of deduplication!

    @patch('datetime.datetime', MockDatetime)
    def test_lockout_above_threshold(self):
        # Manually set core_heat to 10.0 in ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({
                'ledger': {},
                'system_state': {
                    'core_heat': 10.0,
                    'last_processed_timestamp': '2026-03-02T15:00:00Z'
                }
            }, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Run should raise ThermalOverloadError and record refusal in ledger (no silent drains)
        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        self.assertIn("Thermal Lockout", str(ctx.exception))
        self.assertIn("Wait for dissipation", str(ctx.exception))

        # Check ledger has recorded 'refused'
        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['ledger'][dna]['terminal_outcome'], 'refused')

    @patch('datetime.datetime', MockDatetime)
    def test_heat_decay_over_time(self):
        # Manually set heat to 6.0
        with open(self.ledger_path, 'w') as f:
            json.dump({
                'ledger': {},
                'system_state': {
                    'core_heat': 6.0,
                    'last_processed_timestamp': '2026-03-02T15:00:00Z'
                }
            }, f)

        # Mock time to 8 seconds later (decay: 8 * 0.5 = 4.0 units. Current heat: 6.0 - 4.0 = 2.0)
        MockDatetime.set_now('2026-03-02T15:00:08Z')

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # adds 2.0 -> final should be 4.0

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 4.0)

    @patch('datetime.datetime', MockDatetime)
    def test_no_silent_drains_on_overload(self):
        # Manually trigger lockout heat
        with open(self.ledger_path, 'w') as f:
            json.dump({
                'ledger': {},
                'system_state': {
                    'core_heat': 10.0,
                    'last_processed_timestamp': '2026-03-02T15:00:00Z'
                }
            }, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Simulate the watcher / main runner logic. When run_batch fails with ThermalOverloadError,
        # the input file is not cleared.
        try:
            run_batch()
        except ThermalOverloadError:
            # Expected exception, we do not clear input file
            pass

        # Verify that the input file still contains the sequence
        with open(self.input_file, 'r') as f:
            contents = f.read().strip()
        self.assertEqual(contents, dna)


if __name__ == '__main__':
    unittest.main()

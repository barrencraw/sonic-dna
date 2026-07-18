import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger in structured format
        self.init_time = datetime.datetime(2025, 6, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.save_initial_ledger(0.0, self.init_time)

    def save_initial_ledger(self, heat, last_updated_dt):
        ledger_data = {
            'system_heat': heat,
            'last_updated': last_updated_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ledger': {}
        }
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data, f, indent=2)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_lockout(self):
        # We write 6 valid sequences (prefix VOL) to trigger lockout (20.0 heat per sequence, max is 100.0)
        dnas = ["VOL0890075071" + str(i) for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        # Mock the datetime to stay constant during the run
        class MockDatetime:
            timezone = datetime.timezone
            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return datetime.datetime(2025, 6, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)
                @classmethod
                def fromisoformat(cls, s):
                    return datetime.datetime.fromisoformat(s)

        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        # Load the saved ledger to check heat and outcomes
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 100.0)
        ledger = state['ledger']
        # The first 5 should be success
        for i in range(5):
            self.assertEqual(ledger[dnas[i]]['terminal_outcome'], 'success')
        # The 6th should be refused
        self.assertEqual(ledger[dnas[5]]['terminal_outcome'], 'refused')

    def test_cooling_dissipation(self):
        # Start with 100.0 heat at 12:00:00
        self.save_initial_ledger(100.0, self.init_time)

        # 10 seconds later, heat should dissipate: 100.0 - (10 * 2.0) = 80.0
        # Then, processing 1 sequence should add 20.0 heat, bringing it back to 100.0
        dna = "VOL08900750710"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        class MockDatetime:
            timezone = datetime.timezone
            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return datetime.datetime(2025, 6, 3, 12, 0, 10, tzinfo=datetime.timezone.utc)
                @classmethod
                def fromisoformat(cls, s):
                    return datetime.datetime.fromisoformat(s)

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 100.0)
        self.assertEqual(state['ledger'][dna]['terminal_outcome'], 'success')

    def test_idempotency_does_not_generate_heat(self):
        # Run a sequence once, heat goes to 20.0
        dna = "VOL08900750710"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        class MockDatetime:
            timezone = datetime.timezone
            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return datetime.datetime(2025, 6, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)
                @classmethod
                def fromisoformat(cls, s):
                    return datetime.datetime.fromisoformat(s)

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 20.0)

        # Run it again, it should be skipped and heat should NOT increase
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)
        self.assertEqual(state2['system_heat'], 20.0)

    def test_idle_cooling_records_even_with_zero_sequences(self):
        # Start with 50.0 heat at 12:00:00
        self.save_initial_ledger(50.0, self.init_time)

        # Run with no sequences or empty input at 12:00:15
        # 15 seconds * 2.0 = 30.0 cooling. Heat should be 20.0
        with open(self.input_file, 'w') as f:
            f.write("\n")

        class MockDatetime:
            timezone = datetime.timezone
            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return datetime.datetime(2025, 6, 3, 12, 0, 15, tzinfo=datetime.timezone.utc)
                @classmethod
                def fromisoformat(cls, s):
                    return datetime.datetime.fromisoformat(s)

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 20.0)
        self.assertEqual(state['last_updated'], "2025-06-03T12:00:15Z")

if __name__ == '__main__':
    unittest.main()

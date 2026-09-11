import os
import json
import shutil
import tempfile
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError

class MockDatetime:
    timezone = datetime.timezone
    _current_time = datetime.datetime(2026, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return MockDatetime._current_time

        @classmethod
        def strptime(cls, date_string, format_str):
            return datetime.datetime.strptime(date_string, format_str)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "gain": {"description": "gain level", "min": 0, "max": 999, "pad": 3},
                    "attenuation": {"description": "attenuation level", "min": 0, "max": 999, "pad": 3},
                    "trim": {"description": "trim level", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        MockDatetime._current_time = datetime.datetime(2026, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_lockout(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        # 5 sequences -> 5 * 2.0 = 10.0 heat -> 6th sequence triggers thermal lockout
        sequences = [f"VOL0890075071{i}" for i in range(6)]
        with open(input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", str(cm.exception))

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        system_state = data.get('system_state', {})
        self.assertGreaterEqual(system_state.get('core_heat', 0.0), 10.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        # 4 sequences -> 8.0 heat
        sequences = [f"VOL0890075071{i}" for i in range(4)]
        with open(input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 8.0)

        # Advance time by 10 seconds (10 * 0.5 = 5.0 heat reduction -> heat = 3.0)
        MockDatetime._current_time += datetime.timedelta(seconds=10)

        # Process new sequence
        new_seq = "VOL08900750799"
        with open(input_file, 'w') as f:
            f.write(new_seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        # 8.0 - 5.0 + 2.0 = 5.0
        self.assertAlmostEqual(data['system_state']['core_heat'], 5.0)

if __name__ == '__main__':
    unittest.main()

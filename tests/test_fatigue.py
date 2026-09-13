import sys
from unittest.mock import MagicMock

# Mock non-installed optional audio/GUI dependencies if needed
sys.modules.setdefault("sounddevice", MagicMock())

import os
import json
import shutil
import unittest
import tempfile
import datetime
from unittest.mock import patch

from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class MockDatetimeModule:
    def __init__(self, dt_class):
        self.datetime = dt_class
        self.timezone = datetime.timezone

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
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Copy real rule files to test environment
        real_rules_dir = os.path.join(os.getcwd(), 'rules')
        for item in os.listdir(real_rules_dir):
            s = os.path.join(real_rules_dir, item)
            d = os.path.join(self.rules_dir, item)
            if os.path.isfile(s):
                shutil.copy2(s, d)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_thermal_lockout(self):
        """
        Verify core heat accumulates (+2.0 per sequence) and triggers ThermalOverloadError
        with specific UI message keys when threshold (10.0) is reached.
        """
        # 6 distinct DNA strings (VOL prefix valid DNA)
        dna_sequences = [f"VOL{i:03d}00750712" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Ledger should reflect core_heat >= 10.0
        ledger = load_ledger(self.ledger_path)
        sys_state = ledger.get('_system_state', {})
        self.assertGreaterEqual(sys_state.get('core_heat', 0.0), 10.0)

        # First 5 items processed, 6th caused lockout
        seq_keys = [k for k in ledger if k != '_system_state']
        self.assertEqual(len(seq_keys), 5)

    def test_idempotency_prevents_heat_accumulation(self):
        """
        Duplicate sequences should be deduplicated and not generate additional heat.
        """
        dna = "VOL08900750712"
        base_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class FixedDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return base_time
            @classmethod
            def strptime(cls, date_string, format_string):
                return datetime.datetime.strptime(date_string, format_string)

        mock_mod = MockDatetimeModule(FixedDateTime)

        with patch('utils.dna_ui.datetime', mock_mod):
            # First run: processes 1 sequence (+2.0 heat)
            with open(self.input_file, 'w') as f:
                f.write(dna + "\n")
            run_batch()

            ledger = load_ledger(self.ledger_path)
            heat_after_first = ledger.get('_system_state', {}).get('core_heat', 0.0)
            self.assertEqual(heat_after_first, 2.0)

            # Second run immediately with same time (dedupe hit, 0 new processed)
            with open(self.input_file, 'w') as f:
                f.write(dna + "\n")
            run_batch()

            ledger = load_ledger(self.ledger_path)
            heat_after_second = ledger.get('_system_state', {}).get('core_heat', 0.0)
            self.assertEqual(heat_after_second, 2.0, "Deduplicated sequence must not accumulate heat")

    def test_deterministic_dissipation(self):
        """
        Verify heat dissipates deterministically over time (-0.5 units/sec) without RNG.
        """
        dna = "VOL08900750712"
        base_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class Time1(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return base_time
            @classmethod
            def strptime(cls, date_string, format_string):
                return datetime.datetime.strptime(date_string, format_string)

        mock_mod1 = MockDatetimeModule(Time1)

        with patch('utils.dna_ui.datetime', mock_mod1):
            # Run 1 at t=0 (+2.0 heat)
            with open(self.input_file, 'w') as f:
                f.write(dna + "\n")
            run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['_system_state']['core_heat'], 2.0)

        # Advance time by 2 seconds (dissipates 2.0 * 0.5 = 1.0 heat)
        later_time = base_time + datetime.timedelta(seconds=2)

        class Time2(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return later_time
            @classmethod
            def strptime(cls, date_string, format_string):
                return datetime.datetime.strptime(date_string, format_string)

        mock_mod2 = MockDatetimeModule(Time2)

        dna2 = "VOL00100750712"
        with patch('utils.dna_ui.datetime', mock_mod2):
            with open(self.input_file, 'w') as f:
                f.write(dna2 + "\n")
            run_batch()

        ledger = load_ledger(self.ledger_path)
        # heat: 2.0 initial - 1.0 dissipated + 2.0 for dna2 = 3.0
        self.assertEqual(ledger['_system_state']['core_heat'], 3.0)

    def test_no_silent_drains_input_preserved_on_refusal(self):
        """
        Verify that when thermal overload occurs, the exception is raised and main.process_once
        fails, leaving input file untouched.
        """
        dna_sequences = [f"VOL{i:03d}00750712" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        if 'main' in sys.modules:
            del sys.modules['main']
        import main
        with patch('main.__file__', os.path.join(self.test_dir, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Check input file was NOT cleared (no silent drain)
        with open(self.input_file, 'r') as f:
            remaining = f.read().strip().split('\n')
        self.assertEqual(len(remaining), 6, "Input file must not be cleared when processing is refused")

if __name__ == '__main__':
    unittest.main()

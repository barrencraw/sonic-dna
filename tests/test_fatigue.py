import unittest
import os
import json
import shutil
import tempfile
import datetime as dt_module
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError


class MockDatetime(dt_module.datetime):
    current_time = dt_module.datetime(2026, 3, 2, 12, 0, 0, tzinfo=dt_module.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current_time.replace(tzinfo=None)
        return cls.current_time.astimezone(tz)

    @classmethod
    def advance(cls, seconds):
        cls.current_time = cls.current_time + dt_module.timedelta(seconds=seconds)


class MockDatetimeModule:
    datetime = MockDatetime
    timezone = dt_module.timezone


class TestThermalFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        for fname in os.listdir(os.path.join(self.old_cwd, 'rules')):
            if fname.endswith('.json'):
                shutil.copy(
                    os.path.join(self.old_cwd, 'rules', fname),
                    os.path.join(self.rules_dir, fname)
                )

        MockDatetime.current_time = dt_module.datetime(2026, 3, 2, 12, 0, 0, tzinfo=dt_module.timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_state_persistence(self):
        """Verify that processing 3 sequences adds 6.0 heat units."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write("VOL08900750712\nVOL00000000000\nVOL10000000000\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            data = json.load(f)

        system_state = data.get('system_state', {})
        self.assertEqual(system_state.get('core_heat'), 6.0)

    def test_thermal_lockout_refusal(self):
        """Verify that reaching 10.0 heat units triggers ThermalOverloadError."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        sequences = [f"VOL0000000000{i}" for i in range(6)]
        with open(input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

        err_msg = str(ctx.exception)
        self.assertIn("Thermal Lockout", err_msg)
        self.assertIn("Heat Accumulation", err_msg)
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", err_msg)

    def test_heat_dissipation_over_time(self):
        """Verify heat dissipates at 0.5 units/sec across calls."""
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        with open(input_file, 'w') as f:
            f.write("VOL00000000001\nVOL00000000002\nVOL00000000003\nVOL00000000004\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 8.0)

        MockDatetime.advance(8)

        with open(input_file, 'w') as f:
            f.write("VOL00000000005\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 6.0)


if __name__ == '__main__':
    unittest.main()

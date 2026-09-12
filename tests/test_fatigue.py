import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

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

        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_thermal_overload_and_refusal_message_keys(self):
        """Verify that pushing batch processing over the 10.0 heat limit raises ThermalOverloadError with required UI message keys."""
        # 6 valid Volume sequence lines * 2.0 heat = 12.0 projected heat > 10.0 threshold
        dnas = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.reason, "Thermal Lockout")
        self.assertEqual(err.hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    def test_idempotency_no_double_heat(self):
        """Verify idempotency: re-running already processed keys does not accumulate heat twice."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch() # Adds 2.0 heat

        ledger_after_first = load_ledger(self.ledger_path)
        heat_after_first = ledger_after_first.get('system_state', {}).get('core_heat')
        self.assertEqual(heat_after_first, 2.0)

        # Re-run same DNA sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch() # Should skip processing and not add heat

        ledger_after_second = load_ledger(self.ledger_path)
        heat_after_second = ledger_after_second.get('system_state', {}).get('core_heat')
        self.assertEqual(heat_after_second, 2.0)

    def test_no_silent_drains(self):
        """Verify no silent drains: when ThermalOverloadError occurs, system state is preserved and no partial/silent updates occur."""
        # Process 4 items -> 8.0 heat
        dnas_4 = [f"VOL0890075071{i}" for i in range(4)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dnas_4) + "\n")
        run_batch()

        ledger_before = load_ledger(self.ledger_path)
        self.assertEqual(ledger_before['system_state']['core_heat'], 8.0)

        # Try adding 2 new sequences -> total projected 8.0 + 4.0 = 12.0 > 10.0
        new_dnas = ["VOL08900750714", "VOL08900750715"]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_dnas) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        ledger_after = load_ledger(self.ledger_path)
        # New DNA keys should NOT be added to ledger
        self.assertNotIn("VOL08900750714", ledger_after)
        self.assertNotIn("VOL08900750715", ledger_after)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
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

        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_idempotency(self):
        """Proof: Heat applied exactly once per processed item; 0 heat on duplicate (idempotency)."""
        dna = "VOL08900750712"

        # 1. Process single item at t = 1000.0
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('time.time', return_value=1000.0):
            run_batch()

        ledger = load_ledger(self.ledger_path)
        sys_state = ledger.get("__system_state__", {})
        self.assertEqual(sys_state.get("core_heat"), 2.0, "Heat should increase by 2.0 for 1 processed item")

        # 2. Re-process exact same item immediately at t = 1000.0 (Idempotent deduplication)
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('time.time', return_value=1000.0):
            run_batch()

        ledger = load_ledger(self.ledger_path)
        sys_state = ledger.get("__system_state__", {})
        self.assertEqual(sys_state.get("core_heat"), 2.0, "Duplicate item should cause 0 heat accumulation")

    def test_thermal_dissipation_and_lockout_refusal(self):
        """Proof: No silent drains; heat dissipates deterministically, thermal lockout triggers on overload with indifferent UI messages."""
        # 5 items = 10.0 heat (hits max threshold)
        dnas = [f"VOL0000000000{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with patch('time.time', return_value=1000.0):
            run_batch()

        ledger = load_ledger(self.ledger_path)
        sys_state = ledger.get("__system_state__", {})
        self.assertEqual(sys_state.get("core_heat"), 10.0)

        # Immediate next invocation at t = 1000.0 should trigger ThermalOverloadError refusal
        new_dna = "VOL00000000099"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with patch('time.time', return_value=1000.0):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

            err = cm.exception
            self.assertEqual(err.consequence_applied, "Heat Accumulation")
            self.assertEqual(err.refusal_reason, "Thermal Lockout")
            self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Deterministic dissipation: wait 10 seconds (cooling rate 0.5 heat/sec -> heat drops by 5.0)
        with patch('time.time', return_value=1010.0):
            run_batch() # Should now succeed because current heat (10.0 - 5.0 + 2.0) = 7.0 <= 10.0

        ledger = load_ledger(self.ledger_path)
        sys_state = ledger.get("__system_state__", {})
        self.assertEqual(sys_state.get("core_heat"), 7.0)
        self.assertIn(new_dna, ledger)

if __name__ == '__main__':
    unittest.main()

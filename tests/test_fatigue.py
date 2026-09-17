import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
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
        """Test heat accumulates per sequence processed, and deduplication causes zero heat addition."""
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertIn("_system_state", ledger)
        self.assertAlmostEqual(ledger["_system_state"]["core_heat"], 2.0)

        # Re-running same DNA (idempotent step)
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        # Core heat should not increase for duplicate DNA string
        self.assertAlmostEqual(ledger["_system_state"]["core_heat"], 2.0)

    def test_thermal_lockout_and_messages(self):
        """Test lockout triggers when heat >= 10.0 and raises ThermalOverloadError with UI messages."""
        dnas = [f"VOL0890075071{i}" for i in range(6)] # 6 sequences * 2.0 heat = 12.0 heat threshold exceeded
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, UI_MESSAGES["CONSEQUENCE_APPLIED"])
        self.assertEqual(err.refusal_reason, UI_MESSAGES["REFUSAL_REASON"])
        self.assertEqual(err.next_action_hint, UI_MESSAGES["NEXT_ACTION_HINT"])
        self.assertIn("The system is indifferent to your deadlines.", str(err))

    def test_heat_dissipation_over_time(self):
        """Test heat dissipates over time at 0.5 units/sec."""
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        fake_now = 1000.0
        with patch('time.time', return_value=fake_now):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger["_system_state"]["core_heat"], 2.0)

        # Advance fake time by 2 seconds (heat dissipates by 2 * 0.5 = 1.0 unit -> heat should be 1.0 + 2.0 = 3.0 after next)
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        with patch('time.time', return_value=fake_now + 2.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger["_system_state"]["core_heat"], 3.0)

if __name__ == '__main__':
    unittest.main()

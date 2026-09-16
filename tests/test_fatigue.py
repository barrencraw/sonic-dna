import os
import json
import time
import shutil
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError
import main as main_entry

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
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

    def test_heat_accumulation_and_lockout(self):
        """5 sequences generate 10.0 heat units. 6th sequence in batch triggers Thermal Lockout."""
        fixed_time = 1000.0
        sequences = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        # Mock time so no time elapses during batch
        with patch('time.time', return_value=fixed_time):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(err.CONSEQUENCE_APPLIED, "Heat Accumulation")
        self.assertEqual(err.REFUSAL_REASON, "Thermal Lockout")
        self.assertEqual(err.NEXT_ACTION_HINT, "Wait for dissipation. The system is indifferent to your deadlines.")

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        self.assertIn("_system_state", ledger)
        self.assertAlmostEqual(ledger["_system_state"]["core_heat"], 10.0)
        # First 5 sequences processed
        for seq in sequences[:5]:
            self.assertIn(seq, ledger)
        # 6th sequence was refused and NOT in ledger
        self.assertNotIn(sequences[5], ledger)

    def test_idempotency_does_not_generate_heat(self):
        """Deduplicated requests hit idempotency check and do not accumulate heat."""
        fixed_time = 1000.0
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('time.time', return_value=fixed_time):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        initial_heat = ledger["_system_state"]["core_heat"]
        self.assertAlmostEqual(initial_heat, 2.0)

        # Repeat processing same DNA at same timestamp
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('time.time', return_value=fixed_time):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        subsequent_heat = ledger["_system_state"]["core_heat"]
        self.assertAlmostEqual(subsequent_heat, initial_heat)

    def test_heat_dissipation_over_time(self):
        """Core heat dissipates at 0.5 units/second allowing processing after waiting."""
        start_time = 1000.0
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('time.time', return_value=start_time):
            run_batch()

        # At start_time, heat is 10.0
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger["_system_state"]["core_heat"], 10.0)

        # Simulate 10 seconds passing (dissipates 10 * 0.5 = 5.0 heat -> remaining heat = 5.0)
        future_time = start_time + 10.0
        seq_6 = "VOL08900750719"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(seq_6 + "\n")

        with patch('time.time', return_value=future_time):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        # Heat was 5.0 after decay, plus 2.0 for seq_6 = 7.0
        self.assertAlmostEqual(ledger["_system_state"]["core_heat"], 7.0)
        self.assertIn(seq_6, ledger)

    def test_no_silent_drains(self):
        """Refused sequences on thermal overload are NOT cleared from toSequence.txt."""
        fixed_time = 1000.0
        sequences = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('time.time', return_value=fixed_time):
            with self.assertRaises(SystemExit):
                main_entry.process_once()

        # Verify input file was NOT cleared
        with open(self.input_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        self.assertEqual(content, "\n".join(sequences))

if __name__ == '__main__':
    unittest.main()

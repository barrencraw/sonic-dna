import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty state and ledger
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 0.0}, f)
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_noise(self):
        # VOL amp=500 -> heat_gain = 0.1 + (500/500) = 1.1
        # Need 5 sequences to cross 5.0 heat (passive dissipation -0.5 per run)
        # Sequence 1: Heat starts 0.0 -> dissipation -> 0.0 + 1.1 = 1.1
        # Sequence 2: Heat starts 1.1 -> dissipation 0.6 -> 0.6 + 1.1 = 1.7
        # Actually dissipation is per main() call.
        # Let's process 10 sequences in one batch.
        # Initial Heat = 0.0
        # dissipation = -0.5 -> 0.0
        # Sequence 1: heat + 1.1 = 1.1
        # Sequence 2: heat + 1.1 = 2.2
        # Sequence 3: heat + 1.1 = 3.3
        # Sequence 4: heat + 1.1 = 4.4
        # Sequence 5: heat + 1.1 = 5.5
        # Sequence 6: should have noise applied (heat 5.5 > 5.0)

        dna_list = [f"VOL{str(500).zfill(4)}0750712" for i in range(10)]
        # Make them unique to avoid idempotency deduplication within the same batch if needed,
        # but actually ledger update is per sequence now.
        # Wait, if they are the same string, they hit idempotency.
        unique_dna = [f"VOL{str(500).zfill(4)}0{str(i).zfill(2)}0712" for i in range(10)]

        with open(self.input_file, 'w') as f:
            for dna in unique_dna:
                f.write(dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)

        # Heat should be around 11.0 (10 * 1.1)
        self.assertGreater(state['system_heat'], 5.0)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Entries 0-4 (seq 1-5) should be normal (heat <= 5.0 when starting parse)
        # Entry 5 (seq 6) starts with heat 5.5 -> noise!
        # amp was 500. 500 * 0.9 = 450.0
        self.assertEqual(data[0]['parsed']['amp'], 500)
        self.assertEqual(data[5]['parsed']['amp'], 450.0)

    def test_thermal_overload_refusal(self):
        # Set initial heat high
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        dna = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Passive dissipation makes it 10.5. Still > 10.0.
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify ledger does NOT contain the refused DNA
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna, ledger)

    def test_idempotency_no_extra_heat(self):
        dna = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 0.0 -> 0.0 (diss) + 1.1 = 1.1

        with open(self.state_path, 'r') as f:
            heat1 = json.load(f)['system_heat']

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 1.1 -> 0.6 (diss) + 0 (idempotency hit) = 0.6

        with open(self.state_path, 'r') as f:
            heat2 = json.load(f)['system_heat']

        self.assertEqual(heat2, 0.6)

if __name__ == '__main__':
    unittest.main()

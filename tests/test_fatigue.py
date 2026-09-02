import os
import json
import shutil
import unittest
import time
from datetime import datetime, timezone
from utils.dna_ui import run_batch, ThermalOverloadError, load_ledger

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

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_thermal_lockout_and_ui_messages(self):
        # 6 valid DNA sequences (each adds 2.0 heat units, 5th reaches 10.0, 6th triggers lockout)
        sequences = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn("Heat Accumulation", err_msg)
        self.assertIn("Thermal Lockout", err_msg)
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", err_msg)

        # Verify system state persisted heat in ledger
        full_ledger = load_ledger(self.ledger_path)
        sys_state = full_ledger.get('system_state', {})
        self.assertGreaterEqual(sys_state.get('core_heat', 0.0), 10.0)

if __name__ == '__main__':
    unittest.main()

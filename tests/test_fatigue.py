import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, DNAStatus

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_lockout(self):
        # 21 DNA strings.
        # Item 0: heat 0 -> 5
        # ...
        # Item 19: heat 95 -> 100
        # Item 20: heat 100 -> Check happens BEFORE process, so it's NOT > 100 yet.
        # Wait, if current_heat = 100.0, it is NOT > 100.0.
        # So Item 20 will be processed, heat 100 -> 105.
        # Item 21 will be refused.

        dnas = [f"VOL089007507{i:02d}" for i in range(22)]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        ledger = data['ledger']
        # 21 items processed (0-20), 22nd refused.
        # 21 * 5.0 = 105.0. 22nd item sees 105.0 > 100.0 -> refused.
        self.assertEqual(data['system_heat'], 105.0)

        # Check first 21 are success
        for i in range(21):
            self.assertEqual(ledger[dnas[i]]['terminal_outcome'], DNAStatus.SUCCESS.value, f"DNA {dnas[i]} failed")

        # Check 22nd is refused
        self.assertEqual(ledger[dnas[21]]['terminal_outcome'], DNAStatus.REFUSED.value)

    def test_heat_dissipation(self):
        # 1. Reach lockout
        dnas = [f"VOL089007507{i:02d}" for i in range(23)]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertGreater(data['system_heat'], 100.0)
        self.assertEqual(data['ledger'][dnas[22]]['terminal_outcome'], DNAStatus.REFUSED.value)

        # 2. Simulate time passing
        data['last_processed_timestamp'] -= 40
        with open(self.ledger_path, 'w') as f:
            json.dump(data, f)

        # 3. Process again.
        with open(self.input_file, 'w') as f:
            f.write(dnas[22] + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data2 = json.load(f)

        self.assertEqual(data2['ledger'][dnas[22]]['terminal_outcome'], DNAStatus.SUCCESS.value)
        self.assertLessEqual(data2['system_heat'], 100.0)

    def test_idempotency_refused_retry(self):
        dna = "VOL08900750712"

        ledger_data = {
            "system_heat": 110.0,
            "last_processed_timestamp": time.time(),
            "ledger": {
                dna: {
                    "terminal_outcome": DNAStatus.REFUSED.value,
                    "timestamp": "2023-01-01T00:00:00Z"
                }
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(ledger_data, f)

        ledger_data['last_processed_timestamp'] -= 100
        with open(self.ledger_path, 'w') as f:
            json.dump(ledger_data, f)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['ledger'][dna]['terminal_outcome'], DNAStatus.SUCCESS.value)

if __name__ == '__main__':
    unittest.main()

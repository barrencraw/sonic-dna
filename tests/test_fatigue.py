import os
import json
import shutil
import unittest
import time
import datetime
from utils.dna_ui import main as run_batch, ThermalOverloadError

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

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # HEAT_PER_SEQ = 20.0
        dnas = ["VOL08900750712", "VOL00000000000", "VOL00000000001"]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 60.0)

    def test_thermal_lockout(self):
        # MAX_HEAT = 100.0, HEAT_PER_SEQ = 20.0
        # 6 items should trigger lockout on the 6th item (or after 5)
        # Actually, if heat is 100, it raises. 5 items = 100 heat. 6th item should raise.
        dnas = [f"VOL0890075071{i}" for i in range(7)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 100.0)
        self.assertEqual(len(state['ledger']), 5)

    def test_heat_dissipation(self):
        # Process 2 items -> 40 heat
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\nVOL00000000000\n")

        run_batch()

        # Manually backdate the last_processed_timestamp in the ledger
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Backdate by 10 seconds. COOLING_RATE = 2.0 -> 20 units dissipated.
        old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
        state['last_processed_timestamp'] = old_time.isoformat()

        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Run again with new item
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000001\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Initial 40 - 20 (dissipated) + 20 (new) = 40
        self.assertAlmostEqual(new_state['system_heat'], 40.0, places=1)

    def test_idempotency_does_not_add_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 20 heat

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        self.assertEqual(state1['system_heat'], 20.0)

        run_batch() # Should be a hit, no extra heat

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        # Heat might have dissipated slightly due to time, but shouldn't have increased.
        self.assertLessEqual(state2['system_heat'], 20.0)

if __name__ == '__main__':
    unittest.main()

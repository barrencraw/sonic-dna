import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
        self.backup = os.path.join(self.project_root, 'data_bak')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder)
        os.makedirs(self.output_folder)

        # Initial state
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 100}, f)
        with open(os.path.join(self.data_folder, 'system_messages.json'), 'w') as f:
            json.dump({
                "consequence_applied": "Wear",
                "refusal_reason": "Failure",
                "next_action_hint": "Restore"
            }, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup):
            shutil.move(self.backup, self.data_folder)

    def test_integrity_drain(self):
        # TEX: scarcity 00000, granularity Z, layering 0600, variation 00000, spectral Z
        # layering 600 > 500 -> -10 drain
        dna = "TEX00000Z060000000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 90)

    def test_integrity_restore(self):
        # Set integrity low
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 50}, f)

        # TEX: scarcity 09500, granularity Z, layering 0000, variation 00000, spectral Z
        # scarcity 9500 > 9000 -> +5 restore
        dna = "TEX09500Z000000000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 55)

    def test_system_refusal(self):
        # Set integrity 0
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 0}, f)

        # Normal DNA (not maintenance)
        dna = "VOL05000500500"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'REFUSAL')

    def test_idempotency(self):
        dna = "TEX00000Z060000000Z" # Drain -10
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 100 -> 90
        run_batch() # Should skip because of ledger

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 90, "Integrity should only drain once per DNA")

if __name__ == '__main__':
    unittest.main()

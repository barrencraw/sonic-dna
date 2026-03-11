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
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        # Init state
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 100}, f)
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain(self):
        # TEX: scarcity(5), granularity(1), layering(4), variation(5), spectral(1)
        # Layering > 500 should drain
        dna_complex = "TEX00000Z060000000Z"

        with open(self.input_file, 'w') as f:
            f.write(dna_complex + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 90)

    def test_idempotency_no_double_drain(self):
        dna_complex = "TEX00000Z060000000Z"

        with open(self.input_file, 'w') as f:
            f.write(dna_complex + "\n")
        run_batch()

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_complex + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 90, "Should NOT drain again for same DNA")

    def test_integrity_restore(self):
        # Set integrity to 50
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 50}, f)

        # Scarcity > 9000
        dna_maintenance = "TEX09500Z000100001Z"

        with open(self.input_file, 'w') as f:
            f.write(dna_maintenance + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 55)

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 0}, f)

        dna_normal = "TEX00000Z000100001Z" # Not complex, but also not maintenance

        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger[dna_normal]['terminal_outcome'], 'REFUSAL')

        # Verify maintenance still works at 0
        dna_maintenance = "TEX09500Z000100001Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_maintenance + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna_maintenance]['terminal_outcome'], 'SUCCESS')

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import shutil
import tempfile
from utils.integrity import IntegrityManager
from utils.dna_ui import main as run_batch

class TestSystemIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy rules folder to test_dir
        self.project_root = os.getcwd()
        shutil.copytree(os.path.join(self.project_root, 'rules'), os.path.join(self.test_dir, 'rules'))

        self.integrity_path = os.path.join(self.data_dir, 'system_integrity.json')
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.messages_path = os.path.join(self.data_dir, 'system_messages.json')

        # Setup system messages in test dir
        self.messages = {
            "consequence_applied": "System integrity changed by {change}. Current integrity: {integrity}.",
            "refusal_reason": "Operation refused. Current system integrity (0) is insufficient for non-maintenance DNA strings.",
            "next_action_hint": "Provide a maintenance DNA (TEX scarcity < 1000) to restore system integrity."
        }
        with open(self.messages_path, 'w', encoding='utf-8') as f:
            json.dump(self.messages, f)

        # Change cwd to test_dir for run_batch to find the right paths
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w', encoding='utf-8') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def get_integrity(self):
        if os.path.exists(self.integrity_path):
            with open(self.integrity_path, 'r', encoding='utf-8') as f:
                return json.load(f).get('integrity', 100)
        return 100

    def set_integrity(self, val):
        with open(self.integrity_path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': val}, f)

    def test_integrity_wear(self):
        # Normal wear: -2
        # VOL08900750712
        self.write_dna(["VOL08900750712"])
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

    def test_heavy_load_wear(self):
        # Heavy load: TEX scarcity > 8000 -> -5
        # TEX08001D007600137Z (scarcity 08001)
        self.write_dna(["TEX08001D007600137Z"])
        run_batch()
        self.assertEqual(self.get_integrity(), 95)

    def test_maintenance_restoration(self):
        # Maintenance: TEX scarcity < 1000 -> +10
        # TEX00500D007600137Z (scarcity 00500)
        self.set_integrity(50)
        self.write_dna(["TEX00500D007600137Z"])
        run_batch()
        self.assertEqual(self.get_integrity(), 60)

    def test_integrity_cap(self):
        # Integrity capped at 100
        self.set_integrity(95)
        self.write_dna(["TEX00500D007600137Z"])
        run_batch()
        self.assertEqual(self.get_integrity(), 100)

    def test_refusal_at_zero(self):
        # Refuse non-maintenance DNA at 0 integrity
        self.set_integrity(0)
        self.write_dna(["VOL08900750712"])
        run_batch()
        self.assertEqual(self.get_integrity(), 0)

        # Ensure it's not in the ledger (so it can be retried later)
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r', encoding='utf-8') as f:
                ledger = json.load(f)
                self.assertNotIn("VOL08900750712", ledger)

    def test_maintenance_always_allowed(self):
        # Maintenance allowed even at 0 integrity
        self.set_integrity(0)
        self.write_dna(["TEX00500D007600137Z"])
        run_batch()
        self.assertEqual(self.get_integrity(), 10)

    def test_idempotency_no_drain(self):
        # Processing the same DNA twice shouldn't drain integrity twice
        self.write_dna(["VOL08900750712"])
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

        # Second run with same DNA (already in ledger)
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

if __name__ == '__main__':
    unittest.main()

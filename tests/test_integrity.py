import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        self.integrity_path = os.path.join(self.data_dir, 'system_integrity.json')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.messages_path = os.path.join(self.data_dir, 'system_messages.json')

        with open(self.messages_path, 'w') as f:
            json.dump({
                "consequence_applied": "Integrity loss: {drain} units.",
                "refusal_reason": "Integrity at 0%.",
                "next_action_hint": "Maintenance required."
            }, f)

        # DNA Strings
        # TEX: scarcity(5), granularity(1), layering(4), variation(5), spectral(1)
        self.std_dna = "TEX05000Z010001000Z"  # Standard (layering 100, variation 1000)
        self.complex_dna = "TEX05000Z060008000Z" # Complex (layering 600, variation 8000)
        self.maint_dna = "TEX09500Z010001000Z" # Maintenance (scarcity 9500)

        self.old_cwd = os.getcwd()
        # Copy rules to test dir
        shutil.copytree(os.path.join(self.old_cwd, 'rules'), os.path.join(self.test_dir, 'rules'))
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(os.path.join(self.raw_dir, 'toSequence.txt'), 'w') as f:
            for dna in dna_list:
                f.write(dna + '\n')

    def get_integrity(self):
        if not os.path.exists(self.integrity_path):
            return 100
        with open(self.integrity_path, 'r') as f:
            return json.load(f).get('integrity')

    def test_integrity_drain_and_restore(self):
        # 1. Standard Drain (-2)
        self.write_dna([self.std_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

        # 2. Complex Drain (-10)
        self.write_dna([self.complex_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 88)

        # 3. Maintenance Restore (+5)
        self.write_dna([self.maint_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 93)

    def test_idempotency_no_double_drain(self):
        self.write_dna([self.std_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

        # Re-run same DNA (should be deduped by ledger)
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

    def test_refusal_at_zero(self):
        # Force integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        self.write_dna([self.std_dna])
        run_batch()

        # Should still be 0
        self.assertEqual(self.get_integrity(), 0)

        # Check output for REFUSAL
        with open(os.path.join(self.output_dir, 'toSequence_parsed.json'), 'r') as f:
            results = json.load(f)
            self.assertEqual(results[0]['outcome'], 'REFUSAL')

        # Maintenance should still work at 0
        self.write_dna([self.maint_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 5)

if __name__ == '__main__':
    unittest.main()

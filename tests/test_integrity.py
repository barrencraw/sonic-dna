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
        self.project_root = os.getcwd()

        # Setup data folders
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.out_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.out_dir)

        # Link rules folder
        os.symlink(os.path.join(self.project_root, 'rules'), os.path.join(self.test_dir, 'rules'))

        # Initial integrity state
        self.integrity_file = os.path.join(self.data_dir, 'system_integrity.json')
        with open(self.integrity_file, 'w') as f:
            json.dump({"integrity": 100}, f)

        # Initial messages
        self.messages_file = os.path.join(self.data_dir, 'system_messages.json')
        with open(self.messages_file, 'w') as f:
            json.dump({
                "consequence_applied": "Wear recorded.",
                "refusal_reason": "Refusal: integrity 0.",
                "next_action_hint": "Maintenance required."
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def run_batch_in_test_dir(self):
        old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        try:
            run_batch()
        finally:
            os.chdir(old_cwd)

    def test_wear_and_maintenance(self):
        # 1. Normal DNA (minor wear -2)
        # VOL08900750712 = Volume rule (amp 0890, lr 075, sur 07, head 12)
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        self.run_batch_in_test_dir()

        with open(self.integrity_file, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['integrity'], 98)

        # 2. High scarcity TEX DNA (wear -5)
        # TEX06000D007600137Z (scarcity 6000)
        with open(self.input_file, 'w') as f:
            f.write("TEX06000D007600137Z\n")

        self.run_batch_in_test_dir()

        with open(self.integrity_file, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['integrity'], 93)

        # 3. Idempotency (Same DNA, no double wear)
        with open(self.input_file, 'w') as f:
            f.write("TEX06000D007600137Z\n")

        self.run_batch_in_test_dir()

        with open(self.integrity_file, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['integrity'], 93) # Still 93

        # 4. Maintenance DNA (restore +10)
        # TEX09000D007600137Z (scarcity 9000)
        with open(self.input_file, 'w') as f:
            f.write("TEX09000D007600137Z\n")

        self.run_batch_in_test_dir()

        with open(self.integrity_file, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['integrity'], 100) # Cap at 100

    def test_refusal_at_zero_integrity(self):
        # Set integrity to 0
        with open(self.integrity_file, 'w') as f:
            json.dump({"integrity": 0}, f)

        # 1. Non-maintenance DNA should be refused
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        self.run_batch_in_test_dir()

        # Check output JSON - it should NOT contain VOL08900750712 because it was refused
        parsed_json_path = os.path.join(self.out_dir, 'toSequence_parsed.json')
        if os.path.exists(parsed_json_path):
            with open(parsed_json_path, 'r') as f:
                parsed = json.load(f)
                # Verify that VOL08900750712 is NOT in the parsed list
                self.assertFalse(any(p.get('dna') == "VOL08900750712" for p in parsed))

        # Ledger should NOT have it
        if os.path.exists(self.ledger_file):
            with open(self.ledger_file, 'r') as f:
                ledger = json.load(f)
                self.assertNotIn("VOL08900750712", ledger)

        # 2. Maintenance DNA should still work
        with open(self.input_file, 'w') as f:
            f.write("TEX09000D007600137Z\n")

        self.run_batch_in_test_dir()

        with open(parsed_json_path, 'r') as f:
            parsed = json.load(f)
            # Find the maintenance DNA in parsed results
            self.assertTrue(any(p.get('dna') == "TEX09000D007600137Z" for p in parsed))

        with open(self.integrity_file, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['integrity'], 10)

if __name__ == '__main__':
    unittest.main()

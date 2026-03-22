import unittest
import os
import json
import shutil
from utils.integrity_manager import IntegrityManager
from utils.dna_ui import main as run_batch

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        # Create a test directory structure
        self.test_dir = os.path.join(os.getcwd(), 'test_data_integrity')
        os.makedirs(os.path.join(self.test_dir, 'data', 'raw'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'data', 'output'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'rules'), exist_ok=True)

        # Copy rules
        for rule_file in os.listdir('rules'):
            if rule_file.endswith('.json'):
                shutil.copy(os.path.join('rules', rule_file), os.path.join(self.test_dir, 'rules'))

        # Set working directory to test_dir
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create system_messages.json
        messages = {
            "consequence_applied": "System integrity adjusted. Operation cost deducted.",
            "refusal_reason": "Insufficient system integrity for non-maintenance operations.",
            "next_action_hint": "Submit high-scarcity (TEX > 8000) maintenance DNA to restore integrity."
        }
        with open(os.path.join('data', 'system_messages.json'), 'w') as f:
            json.dump(messages, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(os.path.join('data', 'raw', 'toSequence.txt'), 'w') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def test_integrity_drain_and_restore(self):
        # 1. Start with 100 integrity
        mgr = IntegrityManager(100)

        # 2. Drain with TEX Scarcity < 2000
        # TEX01000A000000000A: scarcity=01000
        wear = mgr.calculate_wear({'rule': 'Texture Complexity', 'values': {'scarcity': 1000}})
        self.assertEqual(wear, -5)
        self.assertEqual(mgr.integrity, 95)

        # 3. Drain with standard wear
        wear = mgr.calculate_wear({'rule': 'Volume', 'values': {'amp': 500}})
        self.assertEqual(wear, -2)
        self.assertEqual(mgr.integrity, 93)

        # 4. Restore with TEX Scarcity > 8000
        wear = mgr.calculate_wear({'rule': 'Texture Complexity', 'values': {'scarcity': 9000}})
        self.assertEqual(wear, 7) # Capped at 100 (93 + 10 = 103 -> 100)
        self.assertEqual(mgr.integrity, 100)

    def test_refusal_logic(self):
        # 1. Set integrity to 0
        with open(os.path.join('data', 'system_integrity.json'), 'w') as f:
            json.dump({"integrity": 0}, f)

        # 2. Try to process a non-maintenance string
        # VOL08900750712
        self.write_dna(["VOL08900750712"])
        run_batch()

        # 3. Check that it's NOT in the ledger and NOT in parsed output
        if os.path.exists(os.path.join('data', 'processed_ledger.json')):
            with open(os.path.join('data', 'processed_ledger.json'), 'r') as f:
                ledger = json.load(f)
            self.assertNotIn("VOL08900750712", ledger)

        if os.path.exists(os.path.join('data', 'output', 'toSequence_parsed.json')):
            with open(os.path.join('data', 'output', 'toSequence_parsed.json'), 'r') as f:
                parsed = json.load(f)
            self.assertEqual(len(parsed), 0)

        # 4. Process a maintenance string (TEX Scarcity > 8000)
        # TEX09000A000000000A
        maintenance_dna = "TEX09000A000000000A"
        self.write_dna([maintenance_dna])
        run_batch()

        # 5. Check that it IS in the ledger and integrity is restored
        with open(os.path.join('data', 'processed_ledger.json'), 'r') as f:
            ledger = json.load(f)
        self.assertIn(maintenance_dna, ledger)
        self.assertEqual(ledger[maintenance_dna]["terminal_outcome"], "SUCCESS")

        with open(os.path.join('data', 'system_integrity.json'), 'r') as f:
            integrity = json.load(f)
        self.assertEqual(integrity["integrity"], 10)

    def test_idempotency_no_silent_drains(self):
        # 1. Process a string once
        dna = "VOL08900750712"
        self.write_dna([dna])
        run_batch()

        with open(os.path.join('data', 'system_integrity.json'), 'r') as f:
            integrity_v1 = json.load(f)["integrity"]

        # 2. Process the same string again
        self.write_dna([dna])
        run_batch()

        with open(os.path.join('data', 'system_integrity.json'), 'r') as f:
            integrity_v2 = json.load(f)["integrity"]

        # 3. Integrity should not have changed (dedupe hit)
        self.assertEqual(integrity_v1, integrity_v2)

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import shutil
import tempfile
from utils.integrity_manager import IntegrityManager
from utils.dna_ui import main as run_batch

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy rules to test dir
        shutil.copytree('rules', self.rules_dir, dirs_exist_ok=True)

        # Create system messages
        messages = {
            "consequence_applied": "SHIFT",
            "refusal_reason": "REFUSED",
            "next_action_hint": "MAINTAIN"
        }
        with open(os.path.join(self.data_dir, 'system_messages.json'), 'w') as f:
            json.dump(messages, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.integrity_file = os.path.join(self.data_dir, 'system_integrity.json')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Patch os.getcwd for dna_ui
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(dna + '\n')

    def test_integrity_drain_and_restore(self):
        # 1. Complex DNA: Scarcity 0500 ( < 2000) -> -5
        complex_dna = "TEX00500Z000100001Z"
        self.write_dna([complex_dna])
        run_batch()

        with open(self.integrity_file, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['integrity'], 95)

        # 2. Maintenance DNA: Scarcity 9000 ( > 8000) -> +10
        maint_dna = "TEX09000Z000100001Z"
        self.write_dna([maint_dna])
        run_batch()

        with open(self.integrity_file, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['integrity'], 100) # Capped at 100

    def test_refusal_is_not_terminal(self):
        # Set integrity to 0
        with open(self.integrity_file, 'w') as f:
            json.dump({"integrity": 0}, f)

        # Try complex DNA
        complex_dna = "TEX00500Z000100001Z"
        self.write_dna([complex_dna])
        run_batch()

        # Verify NOT in ledger
        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertNotIn(complex_dna, ledger)

        # Restore integrity via maintenance
        maint_dna = "TEX09000Z000100001Z"
        self.write_dna([maint_dna])
        run_batch()

        with open(self.integrity_file, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 10)

        # Now try complex DNA again - should work now
        self.write_dna([complex_dna])
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertEqual(ledger[complex_dna]['terminal_outcome'], 'SUCCESS')

        with open(self.integrity_file, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 5)

if __name__ == '__main__':
    unittest.main()

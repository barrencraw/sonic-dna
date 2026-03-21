import unittest
import os
import json
import shutil
import tempfile
from utils.integrity_manager import IntegrityManager
from utils.dna_ui import main as run_batch

class TestIntegritySystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        self.state_path = os.path.join(self.data_dir, 'system_integrity.json')
        self.messages_path = os.path.join(self.data_dir, 'system_messages.json')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        # Create default messages
        with open(self.messages_path, 'w') as f:
            json.dump({
                "consequence_applied": "System wear recorded.",
                "refusal_reason": "Integrity depleted. Maintenance required.",
                "next_action_hint": "Submit maintenance-grade TEX strings (>8000 scarcity)."
            }, f)

        # Mock project structure for dna_ui
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir)
        # Symlink rules folder
        os.symlink(os.path.join(self.orig_cwd, 'rules'), os.path.join(self.test_dir, 'rules'))

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.test_dir)

    def test_integrity_wear_calculation(self):
        mgr = IntegrityManager(self.state_path, self.messages_path)

        # Standard Wear
        dna_vol = {'rule': 'Volume', 'values': {'amp': 500, 'lr': 50, 'sur': 0, 'head': 12}}
        self.assertEqual(mgr.calculate_wear(dna_vol), -2)

        # High Complexity Wear
        dna_complex = {'rule': 'Texture Complexity', 'values': {'scarcity': 1000}}
        self.assertEqual(mgr.calculate_wear(dna_complex), -5)

        # Maintenance Restoration
        dna_maint = {'rule': 'Texture Complexity', 'values': {'scarcity': 9000}}
        self.assertEqual(mgr.calculate_wear(dna_maint), 10)

    def test_refusal_logic(self):
        # Force integrity to 0
        with open(self.state_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # Create input: 1 standard, 1 maintenance
        # Volume: VOL + amp(4) + lr(3) + sur(2) + head(2) -> VOL05000500012
        # Texture Complexity: TEX + scarcity(5) + granularity(1) + layering(4) + variation(5) + spectral(1)
        # TEX01000Z001005000Z (scarcity 1000, high complexity)
        # TEX09000Z001005000Z (scarcity 9000, maintenance)

        with open(self.input_file, 'w') as f:
            f.write("VOL05000500012\n") # Standard
            f.write("TEX09000Z001005000Z\n") # Maintenance

        run_batch()

        # Load ledger
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)
        else:
            ledger = {}

        self.assertNotIn("VOL05000500012", ledger, "Standard DNA should be refused at 0 integrity")
        self.assertIn("TEX09000Z001005000Z", ledger, "Maintenance DNA should be processed at 0 integrity")

        # Load integrity
        with open(self.state_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['integrity'], 10, "Integrity should have been restored by maintenance")

    def test_idempotency_with_integrity(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL05000500012\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state1 = json.load(f)

        # Run again with same input (it should be in ledger now, but let's re-run)
        # Re-run batch()
        run_batch()

        with open(self.state_path, 'r') as f:
            state2 = json.load(f)

        self.assertEqual(state1['integrity'], state2['integrity'], "Idempotent hit should not drain integrity twice")

if __name__ == '__main__':
    unittest.main()

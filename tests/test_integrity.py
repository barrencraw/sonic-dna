import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

class TestSystemIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Paths
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.integrity_path = os.path.join(self.data_dir, 'system_integrity.json')

        # Mocking the rules folder might be needed if not running from root
        # but the project has a rules/ folder in root.

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create a dummy rules folder (link or copy from original)
        shutil.copytree(os.path.join(self.old_cwd, 'rules'), os.path.join(self.test_dir, 'rules'))

        # Create a dummy data folder with system_messages.json
        os.makedirs(os.path.join(self.test_dir, 'data'), exist_ok=True)
        shutil.copy(os.path.join(self.old_cwd, 'data', 'system_messages.json'),
                    os.path.join(self.test_dir, 'data', 'system_messages.json'))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w') as f:
            for d in dna_list:
                f.write(f"{d}\n")

    def test_wear_and_refusal(self):
        # 1. Start with 100 integrity
        # 2. Process a high-wear DNA (TEX scarcity < 2000)
        # TEX01000Z000000000Z -> Scarcity 1000 (< 2000), wear -5
        # Structure: TEX (3) + scarcity (5) + granularity (1) + layering (4) + variation (5) + spectral (1) = 19 chars
        self.write_dna(["TEX01000Z000000000Z"])
        run_batch(correlation_id="test-1", actor_id="test-actor")

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['integrity'], 95)

        # 3. Process a standard DNA
        # VOL08900750712 -> wear -2
        self.write_dna(["VOL08900750712"])
        run_batch(correlation_id="test-2", actor_id="test-actor")

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['integrity'], 93)

        # 4. Drain integrity to 0
        im = IntegrityManager(self.integrity_path)
        im.integrity = 0
        im.save_state()

        # 5. Attempt to process non-maintenance DNA -> REFUSAL
        # It should NOT be in the ledger
        self.write_dna(["VOL08900750713"])
        run_batch(correlation_id="test-3", actor_id="test-actor")

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
            self.assertNotIn("VOL08900750713", ledger)

        # 6. Process maintenance DNA (TEX scarcity > 8000) -> SUCCESS + Recovery
        # TEX09000Z000000000Z -> Scarcity 9000 (> 8000), recovery +10
        self.write_dna(["TEX09000Z000000000Z"])
        run_batch(correlation_id="test-4", actor_id="test-actor")

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['integrity'], 10)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
            self.assertIn("TEX09000Z000000000Z", ledger)
            self.assertEqual(ledger["TEX09000Z000000000Z"]["terminal_outcome"], "SUCCESS")

    def test_idempotency_with_integrity(self):
        # Ensure that double processing doesn't double wear
        self.write_dna(["VOL08900750712"])
        run_batch(correlation_id="test-5", actor_id="test-actor")

        with open(self.integrity_path, 'r') as f:
            state1 = json.load(f)

        run_batch(correlation_id="test-6", actor_id="test-actor")

        with open(self.integrity_path, 'r') as f:
            state2 = json.load(f)

        self.assertEqual(state1['integrity'], state2['integrity'])

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

class TestSystemIntegrity(unittest.TestCase):
    def setUp(self):
        # Setup a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create necessary folders
        os.makedirs('data/raw')
        os.makedirs('data/output')

        # Copy rules (mock or real)
        shutil.copytree(os.path.join(self.old_cwd, 'rules'), 'rules')

        # Paths
        self.input_file = 'data/raw/toSequence.txt'
        self.integrity_file = 'data/system_integrity.json'
        self.ledger_file = 'data/processed_ledger.json'
        self.json_output = 'data/output/toSequence_parsed.json'

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_strings):
        with open(self.input_file, 'w') as f:
            for dna in dna_strings:
                f.write(f"{dna}\n")

    def get_integrity(self):
        with open(self.integrity_file, 'r') as f:
            return json.load(f)['integrity']

    def test_standard_wear(self):
        # Standard wear is -2
        self.write_dna(["VOL05000500512"]) # Volume is standard
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

    def test_high_complexity_wear(self):
        # TEX with scarcity < 2000 is -5
        self.write_dna(["TEX01000A001000100A"])
        run_batch()
        self.assertEqual(self.get_integrity(), 95)

    def test_maintenance_restoration(self):
        # First drain some integrity
        self.write_dna(["VOL05000500512"])
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

        # Then restore with maintenance (TEX scarcity > 8000 is +10)
        self.write_dna(["TEX09000A001000100A"])
        run_batch()
        # 98 + 10 = 108, capped at 100
        self.assertEqual(self.get_integrity(), 100)

        # Try restoration from lower
        # Drain 2 * 25 = 50
        self.write_dna([f"VOL{i:04}0500512" for i in range(25)])
        run_batch()
        current = self.get_integrity() # 100 - 50 = 50

        self.write_dna(["TEX09500A001000100A"])
        run_batch()
        self.assertEqual(self.get_integrity(), current + 10)

    def test_refusal_at_zero(self):
        # Drain to zero
        # 100 / 5 = 20 high complexity strings
        # Use different strings to avoid idempotency deduplication in the same batch
        # Use 25 strings to be sure it hits 0
        dna_strings = [f"TEX{i:05}A001000100A" for i in range(100, 2600, 100)] # 25 strings
        self.write_dna(dna_strings)
        run_batch()
        self.assertEqual(self.get_integrity(), 0)

        # Try to process standard DNA
        self.write_dna(["VOL05000500512"])
        run_batch()
        self.assertEqual(self.get_integrity(), 0)

        with open(self.json_output, 'r') as f:
            results = json.load(f)
            # Find the result for VOL05000500512
            vol_result = next(r for r in results if r['dna'] == "VOL05000500512")
            self.assertEqual(vol_result['outcome'], "refusal")

    def test_maintenance_bypasses_refusal(self):
        # Drain to zero
        dna_strings = [f"TEX{i:05}A001000100A" for i in range(100, 2600, 100)]
        self.write_dna(dna_strings)
        run_batch()
        self.assertEqual(self.get_integrity(), 0)

        # Process maintenance
        self.write_dna(["TEX09000A001000100A"])
        run_batch()
        self.assertEqual(self.get_integrity(), 10)

        with open(self.json_output, 'r') as f:
            results = json.load(f)
            maint_result = next(r for r in results if r['dna'] == "TEX09000A001000100A")
            self.assertEqual(maint_result['outcome'], "success")

    def test_idempotency_no_double_drain(self):
        # Process once
        self.write_dna(["VOL05000500512"])
        run_batch()
        self.assertEqual(self.get_integrity(), 98)

        # Process again (same string)
        # In a real scenario, the watcher would have cleared the file,
        # but run_batch reads what is there.
        # If we run again with the same file, idempotency should kick in via ledger.
        run_batch()
        self.assertEqual(self.get_integrity(), 98) # Should still be 98

if __name__ == '__main__':
    unittest.main()

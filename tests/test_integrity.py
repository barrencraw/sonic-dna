import unittest
import os
import json
import shutil
import tempfile
from utils.integrity_manager import IntegrityManager
from utils.dna_ui import main as dna_ui_main

class TestSystemIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy rules to test dir
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        shutil.copytree('rules', self.rules_dir)

        # Setup messages
        self.messages_path = os.path.join(self.data_dir, 'system_messages.json')
        with open(self.messages_path, 'w', encoding='utf-8') as f:
            json.dump({
                "consequence_applied": "Drained",
                "refusal_reason": "Refused",
                "next_action_hint": "Hint"
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(os.path.join(self.raw_dir, 'toSequence.txt'), 'w', encoding='utf-8') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def test_integrity_drain_and_restore(self):
        # 100 -> 90 (Complex: Layering 0501 > 500)
        complex_dna = "TEX00000Z050100000Z"
        # 90 -> 95 (Maintenance: Scarcity 9500 > 9000)
        maintenance_dna = "TEX09500Z000000000Z"

        self.write_dna([complex_dna, maintenance_dna])
        dna_ui_main()

        integrity_path = 'data/system_integrity.json'
        with open(integrity_path, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['integrity'], 95)

    def test_refusal_at_zero(self):
        # Drain integrity to 0
        # 10 complex strings (10 * 10 = 100)
        # We need unique strings to avoid deduplication
        dna_list = []
        for i in range(11):
            scarcity = str(i).zfill(5)
            dna_list.append(f"TEX{scarcity}Z050100000Z")

        self.write_dna(dna_list)
        dna_ui_main()

        with open('data/system_integrity.json', 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 0)

        # Now try to process another complex string
        self.write_dna(["TEX00099Z060000000Z"])
        dna_ui_main()

        with open('data/output/toSequence_parsed.json', 'r') as f:
            results = json.load(f)
            # Find the last result
            last_result = results[-1]
            self.assertEqual(last_result['outcome'], "REFUSAL")
            self.assertEqual(last_result['reason'], "Refused")

    def test_maintenance_restores_from_zero(self):
        # Set integrity to 0 manually
        os.makedirs('data', exist_ok=True)
        with open('data/system_integrity.json', 'w') as f:
            json.dump({'integrity': 0}, f)

        # Process maintenance DNA
        maintenance_dna = "TEX09500Z000000000Z"
        self.write_dna([maintenance_dna])
        dna_ui_main()

        with open('data/system_integrity.json', 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 5)

    def test_idempotency_on_refusal(self):
        # Set integrity to 0
        os.makedirs('data', exist_ok=True)
        with open('data/system_integrity.json', 'w') as f:
            json.dump({'integrity': 0}, f)

        complex_dna = "TEX00000Z060000000Z"
        self.write_dna([complex_dna])

        # First run -> REFUSAL
        dna_ui_main()
        with open('data/processed_ledger.json', 'r') as f:
            ledger = json.load(f)
            self.assertEqual(ledger[complex_dna]['terminal_outcome'], "REFUSAL")

        # Second run -> should be deduped (no new processing)
        # If we change integrity to 100, it should still be REFUSAL because it's in the ledger
        with open('data/system_integrity.json', 'w') as f:
            json.dump({'integrity': 100}, f)

        dna_ui_main()
        # Check output doesn't have a new entry for the same DNA
        with open('data/output/toSequence_parsed.json', 'r') as f:
            results = json.load(f)
            # Should only have 1 entry for that DNA
            dna_entries = [r for r in results if r['dna'] == complex_dna]
            self.assertEqual(len(dna_entries), 1)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')
        self.messages_path = os.path.join(self.data_folder, 'system_messages.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)
        with open(self.messages_path, 'w') as f:
            json.dump({
                "consequence_applied": "WEAR_TEST",
                "refusal_reason": "REFUSAL_TEST",
                "next_action_hint": "HINT_TEST"
            }, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain_standard(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 98)

    def test_integrity_drain_high_density(self):
        dna = "TEX01500Z001005000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 95)

    def test_integrity_restore_maintenance(self):
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 50}, f)

        dna = "TEX08500Z001005000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 60)

    def test_refusal_at_zero(self):
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()
        output = f.getvalue()

        self.assertIn("REFUSAL_TEST", output)
        self.assertIn("HINT_TEST", output)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna, ledger)

    def test_maintenance_allowed_at_zero(self):
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        dna = "TEX09000Z001005000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'SUCCESS')

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 10)

    def test_wear_idempotency(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # First run: wear 2 -> 98
        run_batch()
        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 98)

        # Second run: already in ledger, should NOT wear again
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()
        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 98)

    def test_ui_messages_in_output(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()
        output = f.getvalue()

        self.assertIn("WEAR_TEST", output)

if __name__ == '__main__':
    unittest.main()

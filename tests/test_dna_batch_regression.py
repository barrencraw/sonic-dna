import os
import json
import shutil
import unittest
import uuid
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestDNABatchRegression(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.getcwd()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Backup
        self.backup_dir = os.path.join(self.test_dir, 'data_backup_reg')
        if os.path.exists(self.data_dir):
            shutil.copytree(self.data_dir, self.backup_dir, dirs_exist_ok=True)
            shutil.rmtree(self.data_dir)

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)
        if os.path.exists(self.backup_dir):
            shutil.move(self.backup_dir, self.data_dir)

    def test_batch_processing_and_observability(self):
        # Multiple DNA strings
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"
        dna3 = "INVALID_DNA"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n{dna3}\n")

        correlation_id = str(uuid.uuid4())
        actor_id = "test_actor"

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()

        # Check Observability Logs
        self.assertIn(f"step=start correlation_id={correlation_id} actor_id={actor_id}", output)
        self.assertIn(f"step=process_dna idempotency_key={dna1} outcome=SUCCESS", output)
        self.assertIn(f"step=process_dna idempotency_key={dna2} outcome=SUCCESS", output)
        self.assertIn(f"step=process_dna idempotency_key={dna3} outcome=ERROR", output)
        self.assertIn(f"step=complete outcome=SUCCESS correlation_id={correlation_id}", output)

        # Check Ledger
        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)

        self.assertIn(dna1, ledger)
        self.assertEqual(ledger[dna1]['terminal_outcome'], 'SUCCESS')
        self.assertIn(dna2, ledger)
        self.assertEqual(ledger[dna2]['terminal_outcome'], 'SUCCESS')
        self.assertIn(dna3, ledger)
        self.assertEqual(ledger[dna3]['terminal_outcome'], 'ERROR')

        # Check Deduplication
        f2 = io.StringIO()
        with redirect_stdout(f2):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output2 = f2.getvalue()
        self.assertIn(f"step=process_dna idempotency_key={dna1} outcome=DEDUPE", output2)
        self.assertIn("outcome=NO_NEW_DATA", output2)

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, Outcome, ProcessingResult, ParsedDNA

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Backup and clear
        self.backup_folder = os.path.join(self.project_root, 'data_backup_signal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_structured_logging_fields(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        correlation_id = "test-corr-id"
        actor_id = "test-actor"

        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()
        logs = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

        self.assertTrue(len(logs) >= 2, "Should have at least START and END logs")

        required_fields = {
            "timestamp", "correlation_id", "actor_id", "chain_name",
            "step", "outcome", "idempotency_key", "latency_ms"
        }

        for log_line in logs:
            json_str = log_line.replace("[OBSERVABILITY] ", "")
            data = json.loads(json_str)
            self.assertEqual(set(data.keys()), required_fields)
            self.assertEqual(data["correlation_id"], correlation_id)
            self.assertEqual(data["actor_id"], actor_id)
            self.assertEqual(data["chain_name"], "dna_batch_chain")

    def test_canonical_types_usage(self):
        # This test ensures the types are available and correctly defined
        # We can also check if the function returns them or uses them internally
        # (though run_batch returns None, we can verify the Result objects exist)

        res = ProcessingResult(
            dna="test",
            outcome=Outcome.SUCCESS,
            parsed=ParsedDNA(dna="test", rule="rule", values={}),
            idempotency_key="test"
        )
        self.assertEqual(res.outcome, Outcome.SUCCESS)
        self.assertEqual(res.parsed.dna, "test")

if __name__ == '__main__':
    unittest.main()

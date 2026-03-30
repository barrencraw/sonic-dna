import unittest
import io
import json
import os
import shutil
import tempfile
from utils.dna_ui import Outcome, ProcessingResult, ParsedDNA, main as run_batch
from contextlib import redirect_stdout

class TestSignal(unittest.TestCase):
    def setUp(self):
        # Create a temp project root for testing
        self.test_dir = tempfile.mkdtemp()
        self.data_folder = os.path.join(self.test_dir, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Change current working directory to test_dir for run_batch
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # We also need rules/ folder in the test_dir for run_batch to work
        # Copy rules/ from project root
        project_rules = os.path.join(self.old_cwd, 'rules')
        test_rules = os.path.join(self.test_dir, 'rules')
        shutil.copytree(project_rules, test_rules)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_processing_result_naming(self):
        # Regression guard for naming alignment
        pd = ParsedDNA(rule="VOL", values={"v": 1})
        res = ProcessingResult(dna="VOL1", outcome=Outcome.SUCCESS, data=pd)
        self.assertEqual(res.dna, "VOL1")
        self.assertEqual(res.outcome, Outcome.SUCCESS)
        self.assertEqual(res.data.rule, "VOL")

    def test_structured_logs_presence(self):
        # Regression guard for observability hygiene
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr", actor_id="test-actor")

        output = f.getvalue()
        obs_logs = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

        self.assertTrue(len(obs_logs) >= 3, f"Expected at least 3 observability logs (START, STEP, END), got {len(obs_logs)}")

        # Parse one log and check fields
        step_log = None
        for log in obs_logs:
            data = json.loads(log.replace("[OBSERVABILITY] ", ""))
            if data['step'] == 'STEP':
                step_log = data
                break

        self.assertIsNotNone(step_log)
        self.assertEqual(step_log['correlation_id'], "test-corr")
        self.assertEqual(step_log['actor_id'], "test-actor")
        self.assertEqual(step_log['chain_name'], "dna_batch_chain")
        self.assertEqual(step_log['outcome'], "success")
        self.assertIn('latency_ms', step_log)
        self.assertEqual(step_log['idempotency_key'], dna)

if __name__ == '__main__':
    unittest.main()

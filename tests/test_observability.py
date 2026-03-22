import unittest
import os
import json
import shutil
import tempfile
import uuid
from utils.dna_ui import main as run_batch

class TestObservability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_observability_logs_emitted(self):
        dna = "VOL089"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        correlation_id = str(uuid.uuid4())
        actor_id = "test_actor"

        from io import StringIO
        import sys
        captured_output = StringIO()
        sys.stdout = captured_output

        try:
            run_batch(correlation_id=correlation_id, actor_id=actor_id)
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        obs_logs = [line for line in output.split('\n') if "[OBSERVABILITY]" in line]

        self.assertGreater(len(obs_logs), 0, "No observability logs found")

        # Verify first log is 'start'
        first_log = json.loads(obs_logs[0].split("[OBSERVABILITY] ")[1])
        self.assertEqual(first_log['step'], 'start')
        self.assertEqual(first_log['correlation_id'], correlation_id)
        self.assertEqual(first_log['actor_id'], actor_id)

        # Verify 'process_dna' log
        process_logs = [l for l in obs_logs if '"step": "process_dna"' in l and '"outcome": "success"' in l]
        self.assertEqual(len(process_logs), 1)
        process_log = json.loads(process_logs[0].split("[OBSERVABILITY] ")[1])
        self.assertEqual(process_log['idempotency_key'], dna)

        # Verify 'end' log
        last_log = json.loads(obs_logs[-1].split("[OBSERVABILITY] ")[1])
        self.assertEqual(last_log['step'], 'end')
        self.assertEqual(last_log['outcome'], 'success')

    def test_observability_on_error(self):
        # DNA that will fail (wrong length for Volume if it expects 3 digits, but calculator might handle it)
        # Let's use a DNA that will definitely fail RuleParseError if possible
        # Or just mock the calculator to fail

        dna = "INVALID"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        correlation_id = str(uuid.uuid4())

        from io import StringIO
        import sys
        captured_output = StringIO()
        sys.stdout = captured_output

        try:
            run_batch(correlation_id=correlation_id, actor_id="test_actor")
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        obs_logs = [line for line in output.split('\n') if "[OBSERVABILITY]" in line]

        error_logs = [l for l in obs_logs if '"outcome": "ERROR:' in l]
        self.assertGreater(len(error_logs), 0, "No error observability logs found")

        error_log = json.loads(error_logs[0].split("[OBSERVABILITY] ")[1])
        self.assertIn("ERROR", error_log['outcome'])
        self.assertIsNotNone(error_log.get('error'))

if __name__ == '__main__':
    unittest.main()

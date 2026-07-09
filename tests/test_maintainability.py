import unittest
import inspect
import json
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_in_calculator(self):
        """Ensure DNACalculator.parse uses 'dna_sequence' as parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters)

    def test_structured_logging_format(self):
        """Verify that logs follow the JSON_LOG: structured format."""
        # We'll capture stdout and run a small batch
        import os
        import shutil
        import tempfile

        test_dir = tempfile.mkdtemp()
        try:
            old_cwd = os.getcwd()
            os.chdir(test_dir)

            # Setup minimal rules and input
            os.makedirs('rules')
            os.makedirs('data/raw')
            with open('rules/rules_Volume.json', 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "V",
                    "subvars": {"level": {"description": "vol", "min":0, "max":9, "pad":1}}
                }, f)
            with open('data/raw/toSequence.txt', 'w') as f:
                f.write("V1\n")

            f = io.StringIO()
            with redirect_stdout(f):
                run_batch(correlation_id="test-id", actor_id="test-actor")

            output = f.getvalue()
            log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]
            self.assertTrue(len(log_lines) >= 1)

            # Verify fields in the first log line
            first_log = json.loads(log_lines[0][9:])
            required_fields = [
                "timestamp", "correlation_id", "actor_id",
                "chain_name", "step", "outcome", "latency_ms"
            ]
            for field in required_fields:
                self.assertIn(field, first_log)

            self.assertEqual(first_log["correlation_id"], "test-id")
            self.assertEqual(first_log["actor_id"], "test-actor")

            os.chdir(old_cwd)
        finally:
            shutil.rmtree(test_dir)

if __name__ == '__main__':
    unittest.main()

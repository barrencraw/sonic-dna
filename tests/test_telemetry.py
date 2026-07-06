import os
import json
import shutil
import unittest
import tempfile
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestTelemetry(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_structured_logs_emitted(self):
        """Verify that JSON_LOG: prefixed logs are emitted with correct fields."""
        f = io.StringIO()
        correlation_id = "test-uuid-123"

        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id)

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]

        # Should have at least start, process_item, and end
        self.assertGreaterEqual(len(log_lines), 3)

        # Parse and verify the first log (start)
        start_log = json.loads(log_lines[0].replace("JSON_LOG:", ""))
        self.assertEqual(start_log['step'], 'start')
        self.assertEqual(start_log['correlation_id'], correlation_id)
        self.assertIn('timestamp', start_log)

        # Verify the middle log (process_item)
        item_log = json.loads(log_lines[1].replace("JSON_LOG:", ""))
        self.assertEqual(item_log['step'], 'process_item')
        self.assertEqual(item_log['dna_sequence'], 'V100')
        self.assertEqual(item_log['outcome'], 'success')

        # Verify the last log (end)
        end_log = json.loads(log_lines[-1].replace("JSON_LOG:", ""))
        self.assertEqual(end_log['step'], 'end')
        self.assertEqual(end_log['outcome'], 'success')

if __name__ == '__main__':
    unittest.main()

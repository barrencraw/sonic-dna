import unittest
import os
import shutil
import tempfile
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
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

    def test_structured_logging_presence(self):
        """Verify that batch processing emits JSON_LOG prefixed lines."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cid", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]

        self.assertGreater(len(log_lines), 0, "Should have at least one JSON_LOG line")

        # Verify first log is batch_start
        first_log = json.loads(log_lines[0][10:])
        self.assertEqual(first_log["step"], "batch_start")
        self.assertEqual(first_log["correlation_id"], "test-cid")
        self.assertEqual(first_log["actor_id"], "test-actor")

    def test_canonical_naming_dna(self):
        """Verify that the JSON output uses the canonical name 'dna'."""
        run_batch()
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna', data[0], "JSON entry should have canonical key 'dna'")

if __name__ == '__main__':
    unittest.main()

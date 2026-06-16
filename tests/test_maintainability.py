import os
import json
import shutil
import unittest
import tempfile
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
        self.dna_sequence = "V123"
        with open(self.input_file, 'w') as f:
            f.write(self.dna_sequence + "\n")

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

    def test_dna_sequence_key_presence(self):
        """Verify that 'dna_sequence' is used in JSON output instead of 'dna'."""
        run_batch()
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])

    def test_structured_logging_format(self):
        """Verify that structured logs are emitted with the correct fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-id")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]
        self.assertTrue(len(log_lines) > 0, "No structured logs found")

        for line in log_lines:
            log_json = json.loads(line[len("JSON_LOG: "):])
            self.assertIn("correlation_id", log_json)
            self.assertEqual(log_json["correlation_id"], "test-id")
            self.assertIn("chain_name", log_json)
            self.assertIn("step", log_json)
            self.assertIn("outcome", log_json)
            self.assertIn("timestamp", log_json)

if __name__ == '__main__':
    unittest.main()

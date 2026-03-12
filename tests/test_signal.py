import unittest
import os
import sys
import io
import uuid
import json
import shutil
import tempfile
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_observability_logs_format(self):
        correlation_id = str(uuid.uuid4())
        actor_id = "test_actor"

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()
        lines = [line for line in output.split('\n') if "[OBSERVABILITY]" in line]

        self.assertGreaterEqual(len(lines), 3) # start, process_string, terminal

        for line in lines:
            self.assertTrue(line.startswith("[OBSERVABILITY]"))
            self.assertIn(f"correlation_id={correlation_id}", line)
            self.assertIn(f"actor_id={actor_id}", line)
            self.assertIn("timestamp=", line)
            self.assertIn("chain=dna_batch_chain", line)

        # Check specific steps
        steps = [line.split("step=")[1].split()[0] for line in lines]
        self.assertIn("start", steps)
        self.assertIn("process_string", steps)
        self.assertIn("terminal", steps)

if __name__ == '__main__':
    unittest.main()

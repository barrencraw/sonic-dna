import unittest
import os
import shutil
import tempfile
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, Outcome

class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Copy real rules to test dir
        real_rules = os.path.join(os.getcwd(), 'rules')
        for item in os.listdir(real_rules):
            s = os.path.join(real_rules, item)
            d = os.path.join(self.rules_dir, item)
            if os.path.isfile(s):
                shutil.copy2(s, d)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_log_output_format(self):
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(project_root=self.test_dir)

        output = f.getvalue()
        lines = output.strip().split('\n')

        # We expect at least: START, PROCESS, PROCESS_DONE, COMMIT, END
        self.assertGreaterEqual(len(lines), 5)

        correlation_ids = []
        for line in lines:
            parts = line.split(' | ')
            self.assertGreaterEqual(len(parts), 8)
            # ISO8601 timestamp
            self.assertIn('T', parts[0])
            # Correlation ID (UUID)
            self.assertEqual(len(parts[1]), 36)
            correlation_ids.append(parts[1])
            # Chain Name
            self.assertEqual(parts[2], "DNA_BATCH_PARSING")

        # Verify consistent correlation ID
        self.assertEqual(len(set(correlation_ids)), 1, "Correlation IDs should be identical across a single batch")

    def test_outcome_logging(self):
        # 1. Success case
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(project_root=self.test_dir)

        output = f.getvalue()
        self.assertIn("| END | SUCCESS |", output)

        # 2. No DNA case
        with open(self.input_file, 'w') as f:
            f.write("\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(project_root=self.test_dir)

        output = f.getvalue()
        self.assertIn("| END | NO_NEW_DNA |", output)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def test_observability_logs_presence(self):
        """
        Verify that [OBSERVABILITY] logs are present and correctly formatted.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Setup mock project structure
            raw_dir = os.path.join(tmp_dir, 'data', 'raw')
            output_dir = os.path.join(tmp_dir, 'data', 'output')
            rules_dir = os.path.join(tmp_dir, 'rules')
            os.makedirs(raw_dir)
            os.makedirs(output_dir)
            os.makedirs(rules_dir)

            input_file = os.path.join(raw_dir, 'toSequence.txt')
            with open(input_file, 'w') as f:
                f.write("VOL08900750712\n")

            # Mock rule for Volume
            rule_file = os.path.join(rules_dir, 'rules_Volume.json')
            with open(rule_file, 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                        "pan": {"description": "pan", "min": 0, "max": 999, "pad": 3},
                        "gain": {"description": "gain", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            with patch('os.getcwd', return_value=tmp_dir):
                with patch('sys.stdout', new=StringIO()) as fake_out:
                    run_batch(correlation_id="test-id", actor_id="test-actor")
                    output = fake_out.getvalue()

            logs = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

            self.assertGreaterEqual(len(logs), 2, "Should have at least start and terminal logs")

            # Verify first log (start)
            start_log = json.loads(logs[0].replace("[OBSERVABILITY] ", ""))
            self.assertEqual(start_log["correlation_id"], "test-id")
            self.assertEqual(start_log["actor_id"], "test-actor")
            self.assertEqual(start_log["step"], "start")

            # Verify terminal log
            terminal_log = json.loads(logs[-1].replace("[OBSERVABILITY] ", ""))
            self.assertEqual(terminal_log["correlation_id"], "test-id")
            self.assertEqual(terminal_log["step"], "terminal")
            self.assertIn("outcome", terminal_log)
            self.assertIn("latency_ms", terminal_log)

    def test_observability_logs_format(self):
        """
        Ensure each observability log is valid JSON.
        """
        from utils.dna_ui import log_observability
        import json
        from io import StringIO
        import sys

        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            log_observability("cid", "aid", "chain", "step", outcome="SUCCESS")
            output = sys.stdout.getvalue().strip()
        finally:
            sys.stdout = old_stdout

        self.assertTrue(output.startswith("[OBSERVABILITY]"))
        json_part = output.replace("[OBSERVABILITY] ", "")
        data = json.loads(json_part)
        self.assertEqual(data["correlation_id"], "cid")
        self.assertEqual(data["step"], "step")
        self.assertEqual(data["outcome"], "SUCCESS")

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import io
import shutil
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import main as run_batch, Outcome, ProcessingResult

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maintain')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_naming_alignment(self):
        """Verify canonical naming for DTOs."""
        pd = ParsedDNA(rule_name="test", values={})
        self.assertTrue(hasattr(pd, 'rule_name'))
        self.assertTrue(hasattr(pd, 'values'))

        pr = ProcessingResult(outcome=Outcome.SUCCESS)
        self.assertTrue(hasattr(pr, 'outcome'))
        self.assertTrue(hasattr(pr, 'latency_ms'))

    def test_explicit_terminal_states(self):
        """Verify Outcome enum has required states."""
        expected_states = {'success', 'error', 'skipped', 'start', 'end'}
        actual_states = {s.value for s in Outcome}
        for state in expected_states:
            self.assertIn(state, actual_states)

    def test_observability_schema_and_persistence(self):
        """Verify structured log fields and that persistence works (no NameError)."""
        dna = "VOL08900750712"
        input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        lines = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]
        self.assertGreater(len(lines), 0)

        # Check parse_dna log entry
        parse_log = None
        for line in lines:
            entry = json.loads(line.replace('[OBSERVABILITY] ', ''))
            if entry['step'] == 'parse_dna':
                parse_log = entry
                break

        self.assertIsNotNone(parse_log)
        required_keys = {
            'correlation_id', 'actor_id', 'chain_name',
            'step', 'outcome', 'latency_ms',
            'idempotency_key', 'timestamp'
        }
        for key in required_keys:
            self.assertIn(key, parse_log)

        self.assertEqual(parse_log['correlation_id'], "test-corr-id")
        self.assertEqual(parse_log['idempotency_key'], dna)

        # Verify persistence
        json_out = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, 'r') as jf:
            data = json.load(jf)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['dna'], dna)

if __name__ == '__main__':
    unittest.main()

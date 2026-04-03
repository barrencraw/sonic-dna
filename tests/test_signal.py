import unittest
import os
import json
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch
from utils.dna_calculator import ParsedDNA, ProcessingResult

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_signal')
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

    def test_observability_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(logs) >= 2, "Should have at least START and END logs")

        # Check START log
        start_log = json.loads(logs[0].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(start_log['step'], 'START')
        self.assertEqual(start_log['correlation_id'], 'test-corr-id')
        self.assertEqual(start_log['actor_id'], 'test-actor')
        self.assertEqual(start_log['chain_name'], 'dna_batch_chain')

        # Check PARSE_DNA log
        parse_log = [l for l in logs if 'PARSE_DNA' in l][0]
        parse_data = json.loads(parse_log.replace('[OBSERVABILITY] ', ''))
        self.assertEqual(parse_data['step'], 'PARSE_DNA')
        self.assertEqual(parse_data['outcome'], 'success')
        self.assertEqual(parse_data['idempotency_key'], dna)
        self.assertIn('latency_ms', parse_data)

    def test_canonical_naming(self):
        # Verify that ParsedDNA and ProcessingResult are used correctly in terms of structure
        # (Already verified by the fact that run_batch uses them and tests pass,
        # but we can explicitly check the types if we want more rigor)
        from utils.dna_calculator import DNACalculator
        calc = DNACalculator(rules_folder=os.path.join(self.project_root, 'rules'))
        result = calc.parse("VOL08900750712")
        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.rule, "Volume")
        self.assertTrue(hasattr(result, 'dna'))
        self.assertTrue(hasattr(result, 'values'))

        res = ProcessingResult(dna="test", outcome="success", parsed=result)
        self.assertEqual(res.outcome, "success")
        self.assertEqual(res.parsed, result)

if __name__ == '__main__':
    unittest.main()

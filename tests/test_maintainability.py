import unittest
import os
import json
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_calculator import DNACalculator, ParsedDNA
from utils.dna_ui import main as run_batch, Outcome

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maint')
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

    def test_dna_calculator_returns_dto(self):
        calc = DNACalculator(rules_folder=os.path.join(self.project_root, 'rules'))
        dna = "VOL08900750712"
        result = calc.parse(dna)
        self.assertIsInstance(result, ParsedDNA)
        self.assertEqual(result.dna, dna)
        self.assertEqual(result.rule, "Volume")
        self.assertIsInstance(result.values, dict)

    def test_observability_logs_presence(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-correlation-id", actor_id="test-actor")

        output = f.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(obs_logs) >= 4, f"Expected at least 4 observability logs (START, IDEMPOTENCY, PARSE, END), got {len(obs_logs)}")

        found_start = False
        found_end = False
        for log in obs_logs:
            data = json.loads(log[len('[OBSERVABILITY] '):])
            self.assertEqual(data['correlation_id'], "test-correlation-id")
            self.assertEqual(data['actor_id'], "test-actor")
            self.assertIn('chain_name', data)
            self.assertIn('step', data)
            self.assertIn('outcome', data)
            self.assertIn('latency_ms', data)
            self.assertIn('timestamp', data)

            if data['step'] == "START": found_start = True
            if data['step'] == "END": found_end = True

        self.assertTrue(found_start)
        self.assertTrue(found_end)

    def test_ledger_updates_for_all_items(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertIn(dna1, ledger)
        self.assertIn(dna2, ledger)
        self.assertEqual(ledger[dna1]['terminal_outcome'], Outcome.SUCCESS.value)
        self.assertEqual(ledger[dna2]['terminal_outcome'], Outcome.SUCCESS.value)

if __name__ == '__main__':
    unittest.main()

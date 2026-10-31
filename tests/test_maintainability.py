import unittest
import os
import io
import json
import tempfile
import shutil
import inspect
from contextlib import redirect_stdout

from utils.dna_calculator import DNACalculator, Rule
from utils.dna_ui import (
    run_batch,
    log_structured,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    LedgerSaveError,
    AtomicWriteError,
    RuleLoadError,
)

class TestMaintainabilityAndSignal(unittest.TestCase):
    """
    Regression guard tests to prevent backsliding on:
    1. Canonical naming alignment across domain concepts.
    2. Explicit terminal states and typed exception taxonomy.
    3. Observability hygiene and structured log key schemas.
    """

    def test_naming_alignment_in_signatures_and_dto(self):
        # 1. Verify signatures have 'dna_sequence'
        rule_params = list(inspect.signature(Rule.parse).parameters.keys())
        self.assertIn("dna_sequence", rule_params, "Rule.parse should take 'dna_sequence'")

        calc_params = list(inspect.signature(DNACalculator.parse).parameters.keys())
        self.assertIn("dna_sequence", calc_params, "DNACalculator.parse should take 'dna_sequence'")

        # 2. Verify DTO and outputs preserve 'dna_sequence'
        temp_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            os.makedirs(os.path.join(temp_dir, 'data', 'raw'), exist_ok=True)
            os.makedirs(os.path.join(temp_dir, 'data', 'output'), exist_ok=True)
            rules_dir = os.path.join(temp_dir, 'rules')
            os.makedirs(rules_dir, exist_ok=True)

            with open(os.path.join(rules_dir, 'rules_Volume.json'), 'w') as f:
                json.dump({
                    "variable": "Volume",
                    "prefix": "VOL",
                    "subvars": {
                        "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                    }
                }, f)

            input_path = os.path.join(temp_dir, 'data', 'raw', 'toSequence.txt')
            with open(input_path, 'w') as f:
                f.write("VOL123\n")

            run_batch()

            json_out = os.path.join(temp_dir, 'data', 'output', 'toSequence_parsed.json')
            self.assertTrue(os.path.exists(json_out))
            with open(json_out, 'r') as jf:
                parsed = json.load(jf)

            self.assertEqual(len(parsed), 1)
            # Must contain canonical 'dna_sequence' and backward-compatible 'dna'
            self.assertIn("dna_sequence", parsed[0])
            self.assertIn("dna", parsed[0])
            self.assertEqual(parsed[0]["dna_sequence"], "VOL123")
            self.assertEqual(parsed[0]["dna"], "VOL123")

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(temp_dir)

    def test_explicit_terminal_states_and_typed_exceptions(self):
        # Verify DNAStatus enum values
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

        # Verify Exception hierarchy
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(LedgerSaveError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, DNAProcessingError))

    def test_structured_telemetry_schema(self):
        f = io.StringIO()
        with redirect_stdout(f):
            record = log_structured(
                correlation_id="corr-123",
                chain_name="dna_batch_parser",
                step="test_step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=12.34,
                actor_id="test_actor",
                idempotency_key="VOL123",
                outcome_detail="test detail"
            )

        output = f.getvalue()
        self.assertTrue(output.startswith("JSON_LOG:"))

        # Parse json
        json_data = json.loads(output.replace("JSON_LOG:", "").strip())
        required_keys = {
            "timestamp",
            "correlation_id",
            "actor_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "idempotency_key"
        }
        for k in required_keys:
            self.assertIn(k, json_data, f"Missing required telemetry key: {k}")

        self.assertEqual(json_data["correlation_id"], "corr-123")
        self.assertEqual(json_data["actor_id"], "test_actor")
        self.assertEqual(json_data["chain_name"], "dna_batch_parser")
        self.assertEqual(json_data["step"], "test_step")
        self.assertEqual(json_data["outcome"], "success")
        self.assertEqual(json_data["latency_ms"], 12.34)
        self.assertEqual(json_data["idempotency_key"], "VOL123")
        self.assertEqual(json_data["outcome_detail"], "test detail")

if __name__ == '__main__':
    unittest.main()

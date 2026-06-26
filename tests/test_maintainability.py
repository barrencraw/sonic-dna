import unittest
import os
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import DNAStatus, main as run_batch, log_structured
from utils.dna_calculator import DNACalculator

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_in_outputs(self):
        # Verify DNACalculator.parse accepts dna_sequence
        calc = DNACalculator(rules_folder='rules')
        dna = "VOL08900750712"
        try:
            calc.parse(dna_sequence=dna)
        except TypeError:
            self.fail("DNACalculator.parse() does not accept 'dna_sequence' argument")

    def test_structured_logging_format(self):
        f = io.StringIO()
        with redirect_stdout(f):
            log_structured(
                correlation_id="test-id",
                chain_name="test-chain",
                step="test-step",
                outcome=DNAStatus.SUCCESS.value,
                latency_ms=100,
                actor_id="test-actor",
                idempotency_key="test-key"
            )
        output = f.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG: "))

        log_json = json.loads(output.replace("JSON_LOG: ", ""))
        expected_keys = {"timestamp", "correlation_id", "chain_name", "step", "outcome", "latency_ms", "actor_id", "idempotency_key"}
        self.assertTrue(expected_keys.issubset(set(log_json.keys())))
        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["outcome"], "success")

    def test_dna_status_enum(self):
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")

if __name__ == '__main__':
    unittest.main()

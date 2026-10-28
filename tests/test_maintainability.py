import unittest
import inspect
import json
import io
import contextlib
from utils.dna_calculator import DNACalculator
from utils.dna_ui import (
    run_batch,
    log_structured,
    DNAStatus,
    DNAProcessingError,
    InputReadError,
    RuleLoadError,
    PersistenceError,
    AtomicWriteError
)

class TestMaintainability(unittest.TestCase):
    def test_dna_sequence_naming_alignment(self):
        """Assert canonical naming 'dna_sequence' in DNACalculator.parse signature and docstring."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn("dna_sequence", sig.parameters, "DNACalculator.parse must accept 'dna_sequence'")
        doc = inspect.getdoc(DNACalculator.parse) or ""
        self.assertIn("dna_sequence", doc.lower(), "DNACalculator.parse docstring must reference 'dna_sequence'")

    def test_error_taxonomy_inheritance(self):
        """Assert typed error classification inheritance hierarchy."""
        self.assertTrue(issubclass(InputReadError, DNAProcessingError))
        self.assertTrue(issubclass(RuleLoadError, DNAProcessingError))
        self.assertTrue(issubclass(PersistenceError, DNAProcessingError))
        self.assertTrue(issubclass(AtomicWriteError, PersistenceError))
        self.assertTrue(issubclass(AtomicWriteError, DNAProcessingError))

    def test_structured_logging_keys(self):
        """Assert log_structured emits JSON containing all mandatory trace log keys."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            log_structured(
                correlation_id="test-corr-123",
                chain_name="test_chain",
                step="test_step",
                outcome=DNAStatus.SUCCESS,
                latency_ms=1.23,
                actor_id="test_actor",
                idempotency_key="VOL100",
                outcome_detail={"rule": "Volume"}
            )
        output = buf.getvalue().strip()
        self.assertTrue(output.startswith("JSON_LOG:"))
        json_str = output[len("JSON_LOG:"):]
        data = json.loads(json_str)

        required_keys = [
            "timestamp",
            "correlation_id",
            "chain_name",
            "step",
            "outcome",
            "latency_ms",
            "actor_id",
            "idempotency_key"
        ]
        for key in required_keys:
            self.assertIn(key, data, f"Structured log entry missing key '{key}'")

        self.assertEqual(data["correlation_id"], "test-corr-123")
        self.assertEqual(data["chain_name"], "test_chain")
        self.assertEqual(data["step"], "test_step")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["actor_id"], "test_actor")
        self.assertEqual(data["idempotency_key"], "VOL100")

if __name__ == '__main__':
    unittest.main()

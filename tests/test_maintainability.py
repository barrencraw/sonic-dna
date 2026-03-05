import unittest
import io
import sys
import json
from utils.observability import StructuredLogger

class TestMaintainability(unittest.TestCase):
    def test_observability_contract(self):
        """Verify that StructuredLogger emits JSON logs with the [OBSERVABILITY] prefix and required fields."""
        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            logger = StructuredLogger(chain_name="test_chain", correlation_id="test_id")
            logger.start()
            logger.log(step="test_step", outcome="success", extra={"extra_field": "val"})
            logger.end()

            output = captured_output.getvalue().strip().split('\n')

            for line in output:
                self.assertTrue(line.startswith("[OBSERVABILITY] "))
                json_part = line[len("[OBSERVABILITY] "):]
                data = json.loads(json_part)

                required_fields = ["correlation_id", "chain_name", "version", "step", "outcome", "latency_ms", "timestamp"]
                for field in required_fields:
                    self.assertIn(field, data)

                self.assertEqual(data["correlation_id"], "test_id")
                self.assertEqual(data["chain_name"], "test_chain")

            # Verify specific log steps
            start_log = json.loads(output[0][len("[OBSERVABILITY] "):])
            self.assertEqual(start_log["step"], "start")

            terminal_log = json.loads(output[-1][len("[OBSERVABILITY] "):])
            self.assertEqual(terminal_log["step"], "terminal")
            self.assertEqual(terminal_log["outcome"], "success")

        finally:
            sys.stdout = sys.__stdout__

if __name__ == '__main__':
    unittest.main()

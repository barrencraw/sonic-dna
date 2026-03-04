import json
import time

class StructuredLogger:
    def __init__(self, correlation_id=None):
        self.correlation_id = correlation_id

    def log(self, step, outcome, extra=None):
        """
        Emits a structured JSON log prefixed with [OBSERVABILITY].
        """
        log_data = {
            "chain_name": "dna_batch_processing",
            "version": "1.0.0",
            "step": step,
            "outcome": outcome,
            "correlation_id": self.correlation_id,
            "timestamp": time.time()
        }
        if extra:
            log_data.update(extra)

        # Ensure it's printed to stdout as required by the contract
        print(f"[OBSERVABILITY] {json.dumps(log_data)}")

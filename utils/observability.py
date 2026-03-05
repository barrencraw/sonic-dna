import json
import sys
import time
from typing import Optional, Any, Dict

class StructuredLogger:
    """
    Standardized logger for emitting JSON logs to stdout.
    Enforces the [OBSERVABILITY] prefix and common field structure.
    """
    def __init__(self, chain_name: str, correlation_id: Optional[str] = None):
        self.chain_name = chain_name
        self.correlation_id = correlation_id

    def log(self, step: str, outcome: str, latency_ms: Optional[float] = None, **kwargs):
        log_entry = {
            "correlation_id": self.correlation_id,
            "chain_name": self.chain_name,
            "step": step,
            "outcome": outcome,
            "latency_ms": latency_ms,
            "timestamp": time.time(),
            **kwargs
        }
        # Prefixed for easy filtering in logs
        print(f"[OBSERVABILITY] {json.dumps(log_entry)}")
        sys.stdout.flush()

    def start(self, **kwargs):
        self.log(step="start", outcome="processing", **kwargs)

    def transition(self, step: str, **kwargs):
        self.log(step=step, outcome="processing", **kwargs)

    def terminal(self, step: str, outcome: str, **kwargs):
        self.log(step=step, outcome=outcome, **kwargs)

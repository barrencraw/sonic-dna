import json
import time
import sys
from typing import Optional, Any, Dict

class StructuredLogger:
    def __init__(self, chain_name: str, correlation_id: str, version: str = "1.0.0"):
        self.chain_name = chain_name
        self.correlation_id = correlation_id
        self.version = version
        self._start_time = None

    def log(self, step: str, outcome: str = "processing", extra: Optional[Dict[str, Any]] = None):
        latency_ms = 0
        if self._start_time:
            latency_ms = int((time.time() - self._start_time) * 1000)

        payload = {
            "correlation_id": self.correlation_id,
            "chain_name": self.chain_name,
            "version": self.version,
            "step": step,
            "outcome": outcome,
            "latency_ms": latency_ms,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
        if extra:
            payload.update(extra)

        print(f"[OBSERVABILITY] {json.dumps(payload)}")
        sys.stdout.flush()

    def start(self):
        self._start_time = time.time()
        self.log(step="start", outcome="started")

    def end(self, outcome: str = "success", extra: Optional[Dict[str, Any]] = None):
        self.log(step="terminal", outcome=outcome, extra=extra)

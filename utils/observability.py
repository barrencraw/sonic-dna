import json
import sys
import time
from typing import Any, Dict, Optional

class StructuredLogger:
    def __init__(self, chain_name: str, correlation_id: str, version: str = "1.0.0"):
        self.chain_name = chain_name
        self.correlation_id = correlation_id
        self.version = version

    def log(self, step: str, outcome: str, latency_ms: Optional[float] = None, **kwargs: Any):
        log_data = {
            "correlation_id": self.correlation_id,
            "chain_name": self.chain_name,
            "version": self.version,
            "step": step,
            "outcome": outcome,
        }
        if latency_ms is not None:
            log_data["latency_ms"] = latency_ms

        log_data.update(kwargs)

        print(f"[OBSERVABILITY] {json.dumps(log_data)}")
        sys.stdout.flush()

class Timer:
    def __init__(self):
        self.interval = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end = time.perf_counter()
        self.interval = (self.end - self.start) * 1000

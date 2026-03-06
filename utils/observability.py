import json
import time
import sys
from typing import Any, Dict, Optional

class StructuredLogger:
    def __init__(self, chain_name: str, version: str = "1.0.0"):
        self.chain_name = chain_name
        self.version = version

    def log(self, step: str, outcome: str, correlation_id: str,
            latency_ms: Optional[float] = None,
            extra: Optional[Dict[str, Any]] = None):
        """
        Emits a JSON log line prefixed with [OBSERVABILITY].
        """
        log_data = {
            "chain_name": self.chain_name,
            "version": self.version,
            "step": step,
            "outcome": outcome,
            "correlation_id": correlation_id,
            "timestamp": time.time()
        }
        if latency_ms is not None:
            log_data["latency_ms"] = round(latency_ms, 2)
        if extra:
            log_data.update(extra)

        print(f"[OBSERVABILITY] {json.dumps(log_data)}")
        sys.stdout.flush()

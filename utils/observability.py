import json
import time
import sys

class StructuredLogger:
    def __init__(self, service_name):
        self.service_name = service_name

    def log(self, level, message, **kwargs):
        log_entry = {
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            "level": level,
            "message": message,
            "service": self.service_name
        }
        log_entry.update(kwargs)
        print(f"[OBSERVABILITY] {json.dumps(log_entry)}")
        sys.stdout.flush()

    def info(self, message, **kwargs):
        self.log("INFO", message, **kwargs)

    def error(self, message, **kwargs):
        self.log("ERROR", message, **kwargs)

    def warn(self, message, **kwargs):
        self.log("WARN", message, **kwargs)

logger = StructuredLogger("sonic-dna")

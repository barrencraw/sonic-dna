import json
import time
import uuid

class StructuredLogger:
    """
    Standardized structured logger for the SonicDNA observability contract.
    Ensures consistent log fields across the system.
    """
    VERSION = "1.0.0"

    def __init__(self, chain_name, correlation_id=None, causal_event_id=None, **extra_context):
        self.chain_name = chain_name
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.causal_event_id = causal_event_id
        self.context = extra_context
        self.start_time = time.time()
        self.step_start_time = self.start_time

    def _emit(self, step, outcome, extra=None):
        now = time.time()
        latency_ms = int((now - self.start_time) * 1000)
        step_latency_ms = int((now - self.step_start_time) * 1000)

        log_entry = {
            "correlation_id": self.correlation_id,
            "chain_name": self.chain_name,
            "version": self.VERSION,
            "step": step,
            "outcome": outcome,
            "latency_ms": latency_ms,
            "step_latency_ms": step_latency_ms,
            "causal_event_id": self.causal_event_id,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now))
        }

        # Add context fields
        log_entry.update(self.context)
        if extra:
            log_entry.update(extra)

        print(f"[OBSERVABILITY] {json.dumps(log_entry)}")

        # Update step start time for the next step
        self.step_start_time = now

    def start(self, extra=None):
        self._emit("start", "initiated", extra)

    def transition(self, step, outcome="success", extra=None):
        self._emit(step, outcome, extra)

    def terminal(self, outcome, extra=None):
        self._emit("terminal", outcome, extra)

    def error(self, step, error_message, classification=None, cause=None, extra=None):
        err_extra = {
            "error_message": str(error_message),
            "error_classification": classification or "unexpected_error",
            "error_cause": str(cause) if cause else None
        }
        if extra:
            err_extra.update(extra)
        self._emit(step, "error", err_extra)

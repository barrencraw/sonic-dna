import os
import json

class IntegrityManager:
    """
    Manages system operational wear (Fatigue).
    Rules:
    - Base cost: -2 integrity per operation.
    - Complex DNA (TEX scarcity < 2000): additional -3 integrity (Total -5).
    - Maintenance DNA (TEX scarcity > 8000): +10 integrity (Capped at 100).
    - Refusal: if integrity is 0, non-maintenance operations are refused.
    """
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = 100
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except Exception:
                self.integrity = 100

    def save_state(self):
        # State persistence is usually handled by the atomic commit in dna_ui.py
        # but we provide a standalone method for tests.
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f)
            f.flush()
            os.fsync(f.fileno())

    def calculate_wear(self, rule_name, values):
        """
        Returns the delta (int) for the given operation.
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            if scarcity < 2000:
                return -5
            if scarcity > 8000:
                return 10
        return -2

    def apply_wear(self, delta):
        self.integrity = max(0, min(100, self.integrity + delta))

    def is_refusal(self, rule_name, values):
        """
        Returns True if the system refuses this operation.
        Maintenance DNA is never refused.
        """
        if rule_name == "Texture Complexity" and values.get('scarcity', 5000) > 8000:
            return False
        return self.integrity <= 0

import os
import json
from datetime import datetime, timezone

class IntegrityManager:
    def __init__(self, state_file, messages_file):
        self.state_file = state_file
        self.messages_file = messages_file
        self.integrity = 100
        self.messages = {}
        self.load_state()
        self.load_messages()

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = max(0, min(100, data.get('integrity', 100)))
            except Exception:
                self.integrity = 100

    def load_messages(self):
        if os.path.exists(self.messages_file):
            try:
                with open(self.messages_file, 'r', encoding='utf-8') as f:
                    self.messages = json.load(f)
            except Exception:
                self.messages = {}

    def is_maintenance_dna(self, rule_name, values):
        """
        Maintenance DNA is defined as TEX (Texture Complexity) with scarcity > 8000.
        """
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            return scarcity > 8000
        return False

    def calculate_wear(self, rule_name, values):
        """
        Tradeoff logic:
        - High scarcity TEX DNA ( > 5000 ) causes wear (-5).
        - Any other processing causes minor wear (-2).
        - Maintenance DNA (scarcity > 8000) restores integrity (+10).
        """
        if self.is_maintenance_dna(rule_name, values):
            return 10

        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            if scarcity > 5000:
                return -5

        return -2

    def apply_change(self, delta):
        self.integrity = max(0, min(100, self.integrity + delta))

    def can_process(self, rule_name, values):
        """
        Refusal logic: if integrity is 0, only maintenance DNA is allowed.
        """
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)

    def get_refusal_context(self):
        return {
            "reason": self.messages.get("refusal_reason", "Integrity failure."),
            "hint": self.messages.get("next_action_hint", "Restore integrity.")
        }

    def get_success_context(self, delta):
        if delta < 0:
            return {"consequence": self.messages.get("consequence_applied", "System wear recorded.")}
        return {"consequence": "System integrity stabilized."}

    def to_dict(self):
        return {
            "integrity": self.integrity,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

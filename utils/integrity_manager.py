import json
import os

class IntegrityManager:
    def __init__(self, state_path, messages_path):
        self.state_path = state_path
        self.messages_path = messages_path
        self.integrity = self._load_state()
        self.messages = self._load_messages()

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except Exception:
                return 100
        return 100

    def _load_messages(self):
        if os.path.exists(self.messages_path):
            try:
                with open(self.messages_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def get_integrity(self):
        return self.integrity

    def process_dna(self, rule_name, values):
        """
        Updates integrity based on DNA values.
        Returns (integrity_change, message_key or None).
        """
        if rule_name != "Texture Complexity":
            return 0, None

        change = 0
        msg_key = None

        scarcity = values.get('scarcity', 0)
        layering = values.get('layering', 0)
        variation = values.get('variation', 0)

        # Maintenance check
        if scarcity > 9000:
            change = 5
        # Drain check
        elif layering > 500 or variation > 7000:
            change = -10
            msg_key = "consequence_applied"

        self.integrity = max(0, min(100, self.integrity + change))
        return change, msg_key

    def is_refused(self, rule_name, values):
        """
        Returns True if the DNA should be refused based on current integrity.
        Only non-maintenance DNA is refused when integrity is 0.
        """
        if self.integrity > 0:
            return False

        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            if scarcity > 9000:
                return False # Maintenance is always allowed

        return True

    def get_refusal_info(self):
        return {
            "refusal_reason": self.messages.get("refusal_reason", "Refused."),
            "next_action_hint": self.messages.get("next_action_hint", "Unknown.")
        }

    def save_state(self, target_path=None):
        path = target_path or self.state_path
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({"integrity": self.integrity}, f, indent=2)

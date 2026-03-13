import json
import os

class IntegrityManager:
    def __init__(self, integrity_path, messages_path):
        self.integrity_path = integrity_path
        self.messages_path = messages_path
        self.state = self._load_state()
        self.messages = self._load_messages()

    def _load_state(self):
        if os.path.exists(self.integrity_path):
            with open(self.integrity_path, 'r') as f:
                return json.load(f)
        return {"integrity": 100}

    def _load_messages(self):
        if os.path.exists(self.messages_path):
            with open(self.messages_path, 'r') as f:
                return json.load(f)
        return {}

    def get_integrity(self):
        return self.state.get("integrity", 100)

    def calculate_change(self, parsed_dna):
        """
        Calculates integrity change based on DNA.
        - TEX layering > 500 OR variation > 7000: -10 (Wear)
        - TEX scarcity > 9000: +5 (Restore)
        """
        if parsed_dna.get('rule') != 'Texture Complexity':
            return 0

        values = parsed_dna.get('values', {})
        scarcity = values.get('scarcity', 0)
        layering = values.get('layering', 0)
        variation = values.get('variation', 0)

        if layering > 500 or variation > 7000:
            return -10
        if scarcity > 9000:
            return 5
        return 0

    def apply_change(self, change):
        current = self.get_integrity()
        new_integrity = max(0, min(100, current + change))
        self.state["integrity"] = new_integrity
        return new_integrity

    def get_message(self, key):
        return self.messages.get(key, "")

    def save_state(self, path=None):
        target = path or self.integrity_path
        with open(target, 'w') as f:
            json.dump(self.state, f, indent=2)

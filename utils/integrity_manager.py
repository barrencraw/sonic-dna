import json
import os

class IntegrityManager:
    def __init__(self, state_path='data/system_integrity.json', messages_path='data/system_messages.json'):
        self.state_path = state_path
        self.messages_path = messages_path
        self.integrity = 100
        self.messages = {}
        self.load_state()
        self.load_messages()

    def load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except (json.JSONDecodeError, IOError):
                self.integrity = 100
        else:
            self.integrity = 100

    def load_messages(self):
        if os.path.exists(self.messages_path):
            try:
                with open(self.messages_path, 'r', encoding='utf-8') as f:
                    self.messages = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.messages = {}

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f, indent=2)

    def apply_consequences(self, dna_result):
        """
        Applies integrity changes based on the DNA result.
        Returns a dictionary with details if a change occurred, else None.
        """
        if dna_result.get('rule') != "Texture Complexity":
            return None

        values = dna_result.get('values', {})
        layering = values.get('layering', 0)
        variation = values.get('variation', 0)
        scarcity = values.get('scarcity', 0)

        change = 0

        # Rule: high layering (>500) or variation (>7000) drains 10
        if layering > 500 or variation > 7000:
            change = -10
        # Rule: high scarcity (>9000) restores 5
        elif scarcity > 9000:
            change = 5

        if change != 0:
            old_integrity = self.integrity
            self.integrity = max(0, min(100, self.integrity + change))
            if self.integrity != old_integrity:
                return {
                    'old': old_integrity,
                    'new': self.integrity,
                    'change': change,
                    'reason': self.messages.get('consequence_applied', "System integrity adjusted.")
                }

        return None

    def is_refusing(self):
        return self.integrity <= 0

    def get_refusal_info(self):
        return {
            'reason': self.messages.get('refusal_reason', "Process halted."),
            'hint': self.messages.get('next_action_hint', "Stabilize system.")
        }

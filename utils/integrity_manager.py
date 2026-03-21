import json
import os

class IntegrityManager:
    def __init__(self, state_path, messages_path):
        self.state_path = state_path
        self.messages_path = messages_path
        self.integrity = self._load_integrity()
        self.messages = self._load_messages()

    def _load_integrity(self):
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

    def calculate_wear(self, dna_result):
        """
        TEX scarcity < 2000 -> -5
        TEX scarcity > 8000 -> +10 (restoration)
        Any other processing -> -2
        """
        if dna_result['rule'] == 'Texture Complexity':
            scarcity = dna_result['values'].get('scarcity', 5000)
            if scarcity < 2000:
                return -5
            if scarcity > 8000:
                return 10
        return -2

    def apply_consequence(self, delta):
        self.integrity = max(0, min(100, self.integrity + delta))
        return self.messages.get('consequence_applied', 'Consequence applied.')

    def get_refusal(self):
        return {
            'reason': self.messages.get('refusal_reason', 'System refused.'),
            'hint': self.messages.get('next_action_hint', 'Check system status.')
        }

    def is_maintenance(self, dna_result):
        if dna_result['rule'] == 'Texture Complexity':
            return dna_result['values'].get('scarcity', 0) > 8000
        return False

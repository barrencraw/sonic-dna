import os
import json

class IntegrityManager:
    def __init__(self, storage_path, messages_path):
        self.storage_path = storage_path
        self.messages_path = messages_path
        self.integrity = self._load_integrity()
        self.messages = self._load_messages()

    def _load_integrity(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except (json.JSONDecodeError, KeyError):
                return 100
        return 100

    def _load_messages(self):
        if os.path.exists(self.messages_path):
            try:
                with open(self.messages_path, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def apply_consequence(self, result):
        """
        Apply integrity drain/restore based on DNA processing result.
        Returns a message key if a consequence was applied.
        """
        if result.get('rule') != 'Texture Complexity':
            return None

        values = result.get('values', {})
        scarcity = values.get('scarcity', 0)
        layering = values.get('layering', 0)
        variation = values.get('variation', 0)

        change = 0
        if layering > 500 or variation > 7000:
            change = -10
        elif scarcity > 9000:
            change = 5

        if change != 0:
            self.integrity = max(0, min(100, self.integrity + change))
            return "consequence_applied"

        return None

    def is_refused(self, dna_str, result=None):
        """
        Check if processing should be refused due to low integrity.
        Maintenance strings (scarcity > 9000) are never refused.
        """
        if self.integrity > 0:
            return False

        # If we have the result, check if it's maintenance
        if result and result.get('rule') == 'Texture Complexity':
            if result.get('values', {}).get('scarcity', 0) > 9000:
                return False

        return True

    def get_refusal_info(self):
        return {
            'reason': self.messages.get('refusal_reason', 'System integrity depleted.'),
            'hint': self.messages.get('next_action_hint', 'Perform maintenance (high scarcity DNA).')
        }

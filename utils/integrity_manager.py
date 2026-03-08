import json
import os

class IntegrityManager:
    def __init__(self, integrity_path, messages_path):
        self.integrity_path = integrity_path
        self.messages_path = messages_path
        self.integrity = 100
        self.messages = {}
        self.load()

    def load(self):
        if os.path.exists(self.integrity_path):
            try:
                with open(self.integrity_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except (json.JSONDecodeError, IOError):
                self.integrity = 100

        if os.path.exists(self.messages_path):
            try:
                with open(self.messages_path, 'r', encoding='utf-8') as f:
                    self.messages = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.messages = {}

    def save(self):
        with open(self.integrity_path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f, indent=2)

    def is_refusal(self, parsed_dna):
        """
        Refusal if integrity is 0 and it's NOT a maintenance string.
        Maintenance string: TEX DNA with scarcity > 9000.
        """
        if self.integrity > 0:
            return False

        if parsed_dna and parsed_dna['rule'] == 'Texture Complexity':
            scarcity = parsed_dna['values'].get('scarcity', 0)
            if scarcity > 9000:
                return False

        return True

    def apply_consequences(self, parsed_dna):
        """
        Drain 10 if layering > 500 or variation > 7000.
        Restore 5 if scarcity > 9000 (cap 100).
        Returns a message if a consequence was applied.
        """
        if not parsed_dna or parsed_dna['rule'] != 'Texture Complexity':
            return None

        values = parsed_dna['values']
        scarcity = values.get('scarcity', 0)
        layering = values.get('layering', 0)
        variation = values.get('variation', 0)

        msg = None
        # Drain
        if layering > 500 or variation > 7000:
            self.integrity = max(0, self.integrity - 10)
            msg = self.messages.get('consequence_applied')

        # Restore (can happen in the same step, but usually we prioritize restore)
        if scarcity > 9000:
            self.integrity = min(100, self.integrity + 5)
            # We don't necessarily have a message for restore in the spec, but we could add one

        return msg

    def get_refusal_info(self):
        return {
            'refusal_reason': self.messages.get('refusal_reason'),
            'next_action_hint': self.messages.get('next_action_hint')
        }

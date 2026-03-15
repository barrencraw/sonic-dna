#!/usr/bin/env python3
import json
import os

class IntegrityManager:
    def __init__(self, state_path, messages_path):
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
            except Exception:
                self.integrity = 100

    def save_state(self, target_path=None):
        path = target_path or self.state_path
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

    def load_messages(self):
        if os.path.exists(self.messages_path):
            try:
                with open(self.messages_path, 'r', encoding='utf-8') as f:
                    self.messages = json.load(f)
            except Exception:
                self.messages = {}

    def get_refusal_info(self):
        return {
            "refusal_reason": self.messages.get("refusal_reason", "Integrity at 0%."),
            "next_action_hint": self.messages.get("next_action_hint", "Maintenance required.")
        }

    def check_maintenance(self, parsed_dna):
        """Returns True if the DNA is a maintenance string (TEX scarcity > 9000)."""
        if parsed_dna.get('rule') == 'Texture Complexity':
            scarcity = parsed_dna.get('values', {}).get('scarcity', 0)
            return scarcity > 9000
        return False

    def check_high_complexity(self, parsed_dna):
        """Returns True if the DNA is high complexity (TEX layering > 500 or variation > 7000)."""
        if parsed_dna.get('rule') == 'Texture Complexity':
            values = parsed_dna.get('values', {})
            layering = values.get('layering', 0)
            variation = values.get('variation', 0)
            return layering > 500 or variation > 7000
        return False

    def apply_consequence(self, parsed_dna):
        """Applies drain or restore based on DNA. Returns (delta, message)."""
        if self.check_maintenance(parsed_dna):
            delta = 5
            self.integrity = min(100, self.integrity + delta)
            return delta, "Maintenance applied. System components recalibrated."

        if self.check_high_complexity(parsed_dna):
            delta = -10
        else:
            delta = -2

        self.integrity = max(0, self.integrity + delta)
        msg_template = self.messages.get("consequence_applied", "Integrity loss: {drain} units.")
        return delta, msg_template.format(drain=abs(delta))

    def is_stalled(self):
        return self.integrity <= 0

import os
import json

STATE_FILE = os.path.join('data', 'system_integrity.json')

def get_integrity():
    """Returns the current system integrity (0.0 to 100.0)."""
    if not os.path.exists(STATE_FILE):
        return 100.0
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return float(data.get('integrity', 100.0))
    except (json.JSONDecodeError, ValueError, IOError):
        return 100.0

def apply_integrity_delta(delta):
    """Applies a delta to system integrity and persists it, clamped between 0 and 100."""
    current = get_integrity()
    new_val = max(0.0, min(100.0, current + delta))

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'integrity': round(new_val, 2)}, f)
    return new_val

def calculate_integrity_delta(parsed_dna):
    """
    Calculates the integrity impact of a DNA string based on its complexity.
    Returns a float delta.
    """
    rule_name = parsed_dna.get('rule')
    values = parsed_dna.get('values', {})

    if rule_name == 'Texture Complexity':
        layering = values.get('layering', 0)
        variation = values.get('variation', 0)
        scarcity = values.get('scarcity', 10000)

        # Recovery condition: high scarcity, low layering
        if scarcity > 9000 and layering < 10:
            return 15.0

        # Heavy drain condition: high layering or high variation
        if layering > 500 or variation > 7000:
            return -10.0

        # Baseline wear for texture complexity
        return -1.0

    # Baseline wear for any other DNA processing
    return -1.0

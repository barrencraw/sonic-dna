import os
import json
import pytest
import shutil
import tempfile
from utils.integrity_manager import IntegrityManager
from utils.dna_ui import main as run_batch

# Mocking data for tests
TEST_RULES = {
    "rules_Texture_Complexity.json": {
        "variable": "Texture Complexity",
        "prefix": "TEX",
        "subvars": {
            "scarcity": {"min": 0, "max": 10000, "pad": 5, "description": "desc"},
            "granularity": {"class": "Z-A", "description": "desc"},
            "layering": {"min": 0, "max": 1000, "pad": 4, "description": "desc"},
            "variation": {"min": 0, "max": 10000, "pad": 5, "description": "desc"},
            "spectral": {"class": "Z-A", "description": "desc"}
        }
    }
}

@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup folders
        rules_dir = os.path.join(tmpdir, "rules")
        data_dir = os.path.join(tmpdir, "data")
        raw_dir = os.path.join(data_dir, "raw")
        output_dir = os.path.join(data_dir, "output")
        os.makedirs(rules_dir); os.makedirs(raw_dir); os.makedirs(output_dir)

        # Write rule
        for fname, content in TEST_RULES.items():
            with open(os.path.join(rules_dir, fname), 'w') as f:
                json.dump(content, f)

        # Change CWD
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        yield tmpdir
        os.chdir(old_cwd)

def test_integrity_drain(test_env):
    # High layering (501) should drain 10
    dna = "TEX00000Z050100000Z"
    input_file = "data/raw/toSequence.txt"
    with open(input_file, 'w') as f:
        f.write(dna + "\n")

    run_batch()

    integrity_file = "data/system_integrity.json"
    with open(integrity_file, 'r') as f:
        data = json.load(f)
        assert data['integrity'] == 90

def test_integrity_restore(test_env):
    # Initialize with 50 integrity
    integrity_file = "data/system_integrity.json"
    os.makedirs("data", exist_ok=True)
    with open(integrity_file, 'w') as f:
        json.dump({'integrity': 50}, f)

    # High scarcity (9001) should restore 5
    dna = "TEX09001Z000000000Z"
    input_file = "data/raw/toSequence.txt"
    with open(input_file, 'w') as f:
        f.write(dna + "\n")

    run_batch()

    with open(integrity_file, 'r') as f:
        data = json.load(f)
        assert data['integrity'] == 55

def test_integrity_refusal(test_env):
    # Set integrity to 0
    os.makedirs("data", exist_ok=True)
    with open("data/system_integrity.json", 'w') as f:
        json.dump({'integrity': 0}, f)

    # Message keys
    with open("data/system_messages.json", 'w') as f:
        json.dump({
            "consequence_applied": "Adjusted.",
            "refusal_reason": "Process halted.",
            "next_action_hint": "Stabilize system."
        }, f)

    # Complexity DNA should fail with refusal message
    dna = "TEX00000Z050100000Z"
    with open("data/raw/toSequence.txt", 'w') as f:
        f.write(dna + "\n")

    run_batch()

    with open("data/output/toSequence_parsed.json", 'r') as f:
        data = json.load(f)
        # Should contain error with refusal reason
        assert "Process halted. Stabilize system." in data[-1]['error']

def test_integrity_idempotency(test_env):
    # High layering (501) should drain 10 once, even if processed twice
    dna = "TEX00000Z050100000Z"
    input_file = "data/raw/toSequence.txt"

    # First run
    with open(input_file, 'w') as f:
        f.write(dna + "\n")
    run_batch()

    with open("data/system_integrity.json", 'r') as f:
        assert json.load(f)['integrity'] == 90

    # Second run with same DNA - should deduplicate via ledger and NOT drain again
    with open(input_file, 'w') as f:
        f.write(dna + "\n")
    run_batch()

    with open("data/system_integrity.json", 'r') as f:
        assert json.load(f)['integrity'] == 90

def test_integrity_no_silent_drain(test_env):
    # Low complexity DNA should NOT drain
    dna = "TEX00000Z000100001Z"
    input_file = "data/raw/toSequence.txt"
    with open(input_file, 'w') as f:
        f.write(dna + "\n")

    run_batch()

    with open("data/system_integrity.json", 'r') as f:
        assert json.load(f)['integrity'] == 100

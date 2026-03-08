import os
import json
import pytest
import shutil
import tempfile
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

@pytest.fixture
def temp_env():
    # Setup temporary directory structure
    tmp_dir = tempfile.mkdtemp()
    raw_dir = os.path.join(tmp_dir, 'data', 'raw')
    output_dir = os.path.join(tmp_dir, 'data', 'output')
    rules_dir = os.path.join(tmp_dir, 'rules')
    os.makedirs(raw_dir)
    os.makedirs(output_dir)
    os.makedirs(rules_dir)

    # Copy rules
    shutil.copytree('rules', rules_dir, dirs_exist_ok=True)

    # Create system messages
    messages = {
        "consequence_applied": "Drained",
        "refusal_reason": "Refused",
        "next_action_hint": "Hint"
    }
    with open(os.path.join(tmp_dir, 'data', 'system_messages.json'), 'w') as f:
        json.dump(messages, f)

    old_cwd = os.getcwd()
    os.chdir(tmp_dir)
    yield tmp_dir
    os.chdir(old_cwd)
    shutil.rmtree(tmp_dir)

def test_integrity_drain_and_restore(temp_env):
    input_file = 'data/raw/toSequence.txt'
    integrity_file = 'data/system_integrity.json'

    # 1. High complexity should drain integrity
    # TEX: scarcity 00000, granularity Z, layering 0600, variation 00000, spectral Z
    # layering 600 > 500 -> Drain 10
    with open(input_file, 'w') as f:
        f.write("TEX00000Z060000000Z\n")

    run_batch()

    with open(integrity_file, 'r') as f:
        data = json.load(f)
        assert data['integrity'] == 90

    # 2. High scarcity should restore integrity
    # TEX: scarcity 09500, granularity Z, layering 0000, variation 00000, spectral Z
    # scarcity 9500 > 9000 -> Restore 5
    with open(input_file, 'w') as f:
        f.write("TEX09500Z000000000Z\n")

    run_batch()

    with open(integrity_file, 'r') as f:
        data = json.load(f)
        assert data['integrity'] == 95

def test_integrity_refusal(temp_env):
    input_file = 'data/raw/toSequence.txt'
    integrity_file = 'data/system_integrity.json'

    # Set integrity to 0
    with open(integrity_file, 'w') as f:
        json.dump({'integrity': 0}, f)

    # Non-maintenance DNA should be refused
    with open(input_file, 'w') as f:
        f.write("TEX00000Z000000000Z\n")

    run_batch()

    with open('data/output/toSequence_parsed.json', 'r') as f:
        results = json.load(f)
        assert results[0]['terminal_outcome'] == 'refused'
        assert results[0]['refusal_reason'] == "Refused"

    # Maintenance DNA should still work and restore integrity
    with open(input_file, 'w') as f:
        f.write("TEX09500Z000000000Z\n")

    run_batch()

    with open('data/system_integrity.json', 'r') as f:
        data = json.load(f)
        assert data['integrity'] == 5

    with open('data/output/toSequence_parsed.json', 'r') as f:
        results = json.load(f)
        # Find the result for the maintenance DNA
        res = next(r for r in results if r['dna'] == "TEX09500Z000000000Z")
        assert res['terminal_outcome'] == 'success'

def test_integrity_idempotency(temp_env):
    input_file = 'data/raw/toSequence.txt'
    integrity_file = 'data/system_integrity.json'

    dna = "TEX00000Z060000000Z"
    with open(input_file, 'w') as f:
        f.write(dna + "\n")

    run_batch()

    with open(integrity_file, 'r') as f:
        data = json.load(f)
        assert data['integrity'] == 90

    # Processing the same DNA again (e.g. if it stayed in the file)
    # The batch processor uses ledger for idempotency.
    run_batch()

    with open(integrity_file, 'r') as f:
        data = json.load(f)
        # Should still be 90, not 80
        assert data['integrity'] == 90

import os
import json
import shutil
import pytest
from utils.integrity_manager import IntegrityManager
from utils.dna_ui import main as run_batch

@pytest.fixture
def setup_data(tmp_path):
    # Setup data folder structure in tmp_path
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw"
    output_dir = data_dir / "output"
    raw_dir.mkdir(parents=True)
    output_dir.mkdir()

    # Copy rules to tmp_path
    rules_dir = tmp_path / "rules"
    shutil.copytree("rules", rules_dir)

    # Change working directory to tmp_path
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    yield tmp_path

    os.chdir(old_cwd)

def test_integrity_drain_and_restore(setup_data):
    raw_file = setup_data / "data" / "raw" / "toSequence.txt"
    integrity_file = setup_data / "data" / "system_integrity.json"

    # 1. Drain integrity: TEX with high layering (0600)
    # TEX scarcity granularity layering variation spectral
    # TEX 00000 Z 0600 00000 Z
    drain_dna = "TEX00000Z060000000Z"
    with open(raw_file, "w") as f:
        f.write(drain_dna + "\n")

    run_batch()

    with open(integrity_file, "r") as f:
        data = json.load(f)
        assert data["integrity"] == 90

    # 2. Idempotency: Run again with same DNA, integrity should NOT drain again
    with open(raw_file, "w") as f:
        f.write(drain_dna + "\n")

    run_batch()

    with open(integrity_file, "r") as f:
        data = json.load(f)
        assert data["integrity"] == 90 # Still 90

    # 3. Restore integrity: TEX with high scarcity (9500)
    # TEX 09500 Z 0000 00000 Z
    restore_dna = "TEX09500Z000000000Z"
    with open(raw_file, "w") as f:
        f.write(restore_dna + "\n")

    run_batch()

    with open(integrity_file, "r") as f:
        data = json.load(f)
        assert data["integrity"] == 95

def test_integrity_refusal(setup_data):
    raw_file = setup_data / "data" / "raw" / "toSequence.txt"
    integrity_file = setup_data / "data" / "system_integrity.json"
    ledger_file = setup_data / "data" / "processed_ledger.json"

    # Set integrity to 0
    with open(integrity_file, "w") as f:
        json.dump({"integrity": 0}, f)

    # Attempt to process a normal string
    normal_dna = "VOL00000000000" # Should be refused
    with open(raw_file, "w") as f:
        f.write(normal_dna + "\n")

    run_batch()

    with open(ledger_file, "r") as f:
        ledger = json.load(f)
        assert ledger[normal_dna]["terminal_outcome"] == "refused: integrity depleted"

    # Attempt to process a maintenance string
    restore_dna = "TEX09500Z000000000Z"
    with open(raw_file, "w") as f:
        f.write(restore_dna + "\n")

    run_batch()

    with open(ledger_file, "r") as f:
        ledger = json.load(f)
        assert ledger[restore_dna]["terminal_outcome"] == "success"

    with open(integrity_file, "r") as f:
        data = json.load(f)
        assert data["integrity"] == 5 # Restored from 0

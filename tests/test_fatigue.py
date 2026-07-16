import os
import json
import shutil
import pytest
import time
from datetime import datetime, timezone, timedelta
from utils.dna_ui import run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE

@pytest.fixture
def sandbox(tmp_path):
    # Setup temporary directory structure
    raw_folder = tmp_path / "data" / "raw"
    output_folder = tmp_path / "data" / "output"
    raw_folder.mkdir(parents=True)
    output_folder.mkdir(parents=True)

    # Copy rules folder to sandbox
    shutil.copytree("rules", tmp_path / "rules")

    # Mock project root by changing working directory
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    yield tmp_path

    os.chdir(old_cwd)

def test_heat_accumulation(sandbox):
    input_file = sandbox / "data" / "raw" / "toSequence.txt"
    dna = "VOL08900750712"
    with open(input_file, 'w') as f:
        f.write(f"{dna}\n")

    run_batch()

    ledger_path = sandbox / "data" / "processed_ledger.json"
    with open(ledger_path, 'r') as f:
        ledger = json.load(f)

    assert "__system__" in ledger
    assert ledger["__system__"]["heat"] == HEAT_PER_SEQ

def test_thermal_lockout(sandbox):
    input_file = sandbox / "data" / "raw" / "toSequence.txt"
    # Create enough sequences to exceed MAX_HEAT
    num_seqs = int(MAX_HEAT // HEAT_PER_SEQ) + 1
    dna = "VOL08900750712"
    with open(input_file, 'w') as f:
        for i in range(num_seqs):
            f.write(f"VOL{i:011}\n")

    with pytest.raises(ThermalOverloadError) as excinfo:
        run_batch()

    assert "Thermal Lockout" in str(excinfo.value)

    # Verify partial results are committed
    ledger_path = sandbox / "data" / "processed_ledger.json"
    with open(ledger_path, 'r') as f:
        ledger = json.load(f)

    # Should have processed MAX_HEAT / HEAT_PER_SEQ sequences
    processed_count = sum(1 for k in ledger if k != "__system__")
    assert processed_count == int(MAX_HEAT // HEAT_PER_SEQ)
    assert ledger["__system__"]["heat"] == (processed_count * HEAT_PER_SEQ)

def test_cooling_over_time(sandbox):
    ledger_path = sandbox / "data" / "processed_ledger.json"

    # Pre-set high heat in the past
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    initial_ledger = {
        "__system__": {
            "heat": 50.0,
            "last_update": past_time
        }
    }
    with open(ledger_path, 'w') as f:
        json.dump(initial_ledger, f)

    # Create empty input file
    input_file = sandbox / "data" / "raw" / "toSequence.txt"
    with open(input_file, 'w') as f:
        f.write("VOL08900750712\n")

    run_batch()

    with open(ledger_path, 'r') as f:
        ledger = json.load(f)

    # Expected heat: initial - (cooling_rate * 10s) + new_seq_heat
    # 50.0 - (2.0 * 10) + 20.0 = 50.0
    expected_heat = 50.0 - (COOLING_RATE * 10) + HEAT_PER_SEQ
    assert ledger["__system__"]["heat"] == pytest.approx(expected_heat, rel=1e-2)

def test_idempotency_and_atomicity_with_lockout(sandbox):
    input_file = sandbox / "data" / "raw" / "toSequence.txt"
    dna1 = "VOL00000000001"
    dna2 = "VOL00000000002"
    dna3 = "VOL00000000003"
    dna4 = "VOL00000000004"
    dna5 = "VOL00000000005"
    dna6 = "VOL00000000006" # This should trigger lockout if HEAT_PER_SEQ=20 and MAX_HEAT=100

    dnas = [dna1, dna2, dna3, dna4, dna5, dna6]
    with open(input_file, 'w') as f:
        for d in dnas:
            f.write(f"{d}\n")

    with pytest.raises(ThermalOverloadError):
        run_batch()

    ledger_path = sandbox / "data" / "processed_ledger.json"
    with open(ledger_path, 'r') as f:
        ledger = json.load(f)

    assert dna1 in ledger
    assert dna5 in ledger
    assert dna6 not in ledger
    assert ledger["__system__"]["heat"] == 100.0

    # Second run should skip already processed items and still hit lockout immediately for dna6
    with pytest.raises(ThermalOverloadError):
        run_batch()

    with open(ledger_path, 'r') as f:
        ledger2 = json.load(f)

    # Heat might have decreased slightly due to cooling if time elapsed
    assert ledger2["__system__"]["heat"] <= 100.0
    assert dna6 not in ledger2

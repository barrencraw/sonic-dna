import os
import json
import time
import pytest
import shutil
import tempfile
import datetime
from utils.dna_ui import run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE

@pytest.fixture
def sandbox():
    # Setup
    tmp_dir = tempfile.mkdtemp()
    raw_dir = os.path.join(tmp_dir, "data", "raw")
    out_dir = os.path.join(tmp_dir, "data", "output")
    rules_dir = os.path.join(tmp_dir, "rules")
    os.makedirs(raw_dir)
    os.makedirs(out_dir)
    os.makedirs(rules_dir)

    # Mock a rule
    rule_content = {
        "variable": "Volume",
        "prefix": "VOL",
        "subvars": {
            "level": {"description": "volume level", "min": 0, "max": 100, "pad": 3}
        }
    }
    with open(os.path.join(rules_dir, "rule_volume.json"), "w") as f:
        json.dump(rule_content, f)

    old_cwd = os.getcwd()
    os.chdir(tmp_dir)
    yield tmp_dir
    # Teardown
    os.chdir(old_cwd)
    shutil.rmtree(tmp_dir)

def test_heat_accumulation(sandbox):
    input_path = os.path.join("data", "raw", "toSequence.txt")
    with open(input_path, "w") as f:
        f.write("VOL050\nVOL060\n")

    res = run_batch()
    assert res.newly_processed == 2

    ledger_path = os.path.join("data", "processed_ledger.json")
    with open(ledger_path, "r") as f:
        ledger_data = json.load(f)

    expected_heat = HEAT_PER_SEQ * 2
    assert ledger_data["system_heat"] == expected_heat
    assert "last_update" in ledger_data

def test_thermal_lockout(sandbox):
    input_path = os.path.join("data", "raw", "toSequence.txt")
    # Max heat is 100, each seq is 20. 6 seqs should trigger lockout.
    dna_lines = [f"VOL{i:03d}" for i in range(10)]
    with open(input_path, "w") as f:
        f.write("\n".join(dna_lines) + "\n")

    with pytest.raises(ThermalOverloadError):
        run_batch()

    # Check partial results
    ledger_path = os.path.join("data", "processed_ledger.json")
    with open(ledger_path, "r") as f:
        ledger_data = json.load(f)

    # It should have processed exactly 5 (5*20 = 100, 6th would be 120 > 100)
    # Wait, 5th seq: heat + 20 = 100. 100 > 100 is False.
    # Actually, if heat starts at 0:
    # 1: heat=20
    # 2: heat=40
    # 3: heat=60
    # 4: heat=80
    # 5: heat=100
    # 6: 100 + 20 > 100 is True -> Lockout.
    assert len(ledger_data["ledger"]) == 5
    assert ledger_data["system_heat"] == 100.0

def test_cooling(sandbox):
    ledger_path = os.path.join("data", "processed_ledger.json")

    # Manually seed ledger with high heat and old timestamp
    past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
    ledger_data = {
        "ledger": {},
        "system_heat": 50.0,
        "last_update": past_time.isoformat()
    }
    with open(ledger_path, "w") as f:
        json.dump(ledger_data, f)

    # run_batch with no items should still trigger cooling and update ledger
    input_path = os.path.join("data", "raw", "toSequence.txt")
    with open(input_path, "w") as f:
        f.write("")

    run_batch()

    with open(ledger_path, "r") as f:
        new_data = json.load(f)

    # Cooling: 50.0 - (10s * 2.0/s) = 30.0
    # Allow some buffer for execution time
    assert new_data["system_heat"] <= 30.0
    assert new_data["system_heat"] > 25.0

def test_idempotency_no_heat_for_skipped(sandbox):
    input_path = os.path.join("data", "raw", "toSequence.txt")
    with open(input_path, "w") as f:
        f.write("VOL050\n")

    run_batch()
    ledger_path = os.path.join("data", "processed_ledger.json")
    with open(ledger_path, "r") as f:
        heat_after_first = json.load(f)["system_heat"]

    # Run again with same DNA
    run_batch()
    with open(ledger_path, "r") as f:
        heat_after_second = json.load(f)["system_heat"]

    # Heat should have only dissipated, not increased
    assert heat_after_second < heat_after_first

def test_heat_accumulation_on_error(sandbox):
    input_path = os.path.join("data", "raw", "toSequence.txt")
    # Invalid DNA (doesn't start with VOL)
    with open(input_path, "w") as f:
        f.write("INVALID\n")

    res = run_batch()
    assert res.error_count == 1
    assert res.newly_processed == 1

    ledger_path = os.path.join("data", "processed_ledger.json")
    with open(ledger_path, "r") as f:
        ledger_data = json.load(f)

    assert ledger_data["system_heat"] == HEAT_PER_SEQ
    assert ledger_data["ledger"]["INVALID"]["terminal_outcome"] == "ERROR"

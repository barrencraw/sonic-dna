import os
import json
import pytest
import shutil
from utils.dna_ui import main as dna_ui_main
from utils.integrity_manager import IntegrityManager

@pytest.fixture
def clean_data_env():
    # Setup clean data environment
    if os.path.exists('data'):
        shutil.rmtree('data')
    os.makedirs('data/raw', exist_ok=True)
    os.makedirs('data/output', exist_ok=True)

    yield

    # Teardown
    if os.path.exists('data'):
        shutil.rmtree('data')

def test_integrity_drain_complex_dna(clean_data_env):
    # TEX: scarcity 00000, granularity A, layering 0600 (>500), variation 00000, spectral A
    # Calculation: TEX + 00000 + A + 0600 + 00000 + A
    complex_dna = "TEX00000A060000000A"

    with open('data/raw/toSequence.txt', 'w') as f:
        f.write(complex_dna + "\n")

    # Initial integrity should be 100
    mgr = IntegrityManager()
    assert mgr.get_status() == 100

    dna_ui_main()

    # Integrity should have drained by 10
    mgr = IntegrityManager()
    assert mgr.get_status() == 90

def test_integrity_restoration_maintenance_dna(clean_data_env):
    # DRAIN FIRST
    mgr = IntegrityManager()
    mgr.adjust(-50)
    assert mgr.get_status() == 50

    # TEX: scarcity 09500 (>9000), granularity Z, layering 0000, variation 00000, spectral Z
    maintenance_dna = "TEX09500Z000000000Z"

    with open('data/raw/toSequence.txt', 'w') as f:
        f.write(maintenance_dna + "\n")

    dna_ui_main()

    # Integrity should have restored by 5
    mgr = IntegrityManager()
    assert mgr.get_status() == 55

def test_integrity_idempotency(clean_data_env):
    complex_dna = "TEX00000A060000000A"

    with open('data/raw/toSequence.txt', 'w') as f:
        f.write(complex_dna + "\n")

    dna_ui_main()

    mgr = IntegrityManager()
    status_after_first = mgr.get_status()
    assert status_after_first == 90

    # Run again with same DNA
    dna_ui_main()

    mgr = IntegrityManager()
    # Should STILL be 90 because of idempotency (ledger)
    assert mgr.get_status() == 90

def test_integrity_refusal_when_zero(clean_data_env):
    # Set integrity to 0
    mgr = IntegrityManager()
    mgr.adjust(-100)
    assert mgr.get_status() == 0

    complex_dna = "TEX00000A060000000A"
    with open('data/raw/toSequence.txt', 'w') as f:
        f.write(complex_dna + "\n")

    dna_ui_main()

    # Should still be 0, and terminal_outcome should be refusal
    mgr = IntegrityManager()
    assert mgr.get_status() == 0

    with open('data/processed_ledger.json', 'r') as f:
        ledger = json.load(f)
        assert ledger[complex_dna]['terminal_outcome'] == "refusal: low_integrity"

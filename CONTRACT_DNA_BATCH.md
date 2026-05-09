# Chain Contract: DNA Batch Parser

## Overview
This contract defines the behavior, invariants, and observability requirements for the DNA Batch Processing chain in SonicDNA.

## Trigger
- Addition of non-empty content to `data/raw/toSequence.txt`.
- Manual invocation of `utils/dna_ui.py` or `python main.py --once`.

## Inputs
- A list of DNA strings (e.g., `VOL08900750712`, `CLA010050`).
- Persistent state: `data/processed_ledger.json` and `data/system_state.json`.

## Terminal States
- **SUCCESS**: All new DNA strings processed and committed to outputs.
- **ERROR**: Batch failed due to fatal IO or rule loading issues; input file NOT cleared.
- **SKIPPED**: All DNA strings in the current batch were already present in the ledger.

## Invariants
- **Atomicity**: The JSON output (`toSequence_parsed.json`), CSV output (`toSequence_parsed.csv`), and the Idempotency Ledger (`processed_ledger.json`) must be committed as a single atomic transaction using a temporary directory and `os.replace`.
- **Idempotency**: Each unique DNA string serves as its own idempotency key. If a key exists in the ledger, the processing must be skipped for that item.
- **Systemic Feedback (Fatigue/Heat)**:
    - **Passive Dissipation**: 0.5 units of heat are removed at the start of each batch.
    - **Heat Gain**: Processing `VOL` DNA increases `system_heat` by `amp / 100.0`.
    - **Fatigue Penalty**: `CLA` DNA is penalized by `system_heat`:
        - `noise_floor` increased by `int(system_heat)`.
        - `thd` increased by `int(system_heat) * 10`, capped at 1000.
    - **Refusal**: If `system_heat > 10.0`, a `ThermalOverloadError` is raised, and the batch is refused until heat dissipates.

## Required Logs (Standardized Telemetry)
All logs must include: `correlation_id`, `chain_name`, `step`, `outcome`, `latency_ms`, `actor_id`, `idempotency_key`, `timestamp`.

- **Batch Start**: Logged when the process begins.
- **Idempotency Check**: Logged as `SKIPPED` or `SUCCESS` (after processing) for each item.
- **Batch End**: Logged when the atomic commit completes or fails.

## Grep Recipe
```bash
grep "| TELEMETRY |" data/sonicdna.log | jq '.data'
```

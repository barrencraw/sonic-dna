# System Integrity (Fatigue) Domain

## Overview
The DNA Sequencer is a physical system subject to mechanical wear and heat accumulation. This "Fatigue" is represented by the **System Integrity** metric.

## Rules
- **Integrity Range**: 0 to 100.
- **Starting Integrity**: 100.
- **Refusal Threshold**: 0.
    - At 0 integrity, the system enters a hard-refusal state for all non-maintenance tasks.
    - Maintenance DNA strings are the only operations allowed until integrity is above 0.

## Wear Calculation (Deterministic)
Wear is calculated based on the `scarcity` value of the `Texture Complexity` (TEX) rule:

| Category | Condition | Impact |
| :--- | :--- | :--- |
| **Maintenance** | `scarcity < 1000` | +10 restoration (capped at 100) |
| **Heavy Load** | `scarcity > 8000` | -5 wear |
| **Normal Load** | All other cases | -2 wear |

*Note: Wear is applied only once per unique DNA string (idempotency).*

## State Persistence
System integrity is persisted in `data/system_integrity.json`. This file is updated atomically alongside the processing ledger and parsed results.

## UI Tone
System messages regarding integrity must remain indifferent and informative.
- **Refusal**: State the reason clearly without apology.
- **Consequence**: Log the wear application as a system event.
- **Hint**: Provide a next-step hint without comfort.

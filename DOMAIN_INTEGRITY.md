# Domain Integrity: Fatigue Mechanic

## Pressure Axis: Fatigue

The system integrity represents the current 'health' or 'fatigue' level of the DNA processing engine. Continuous processing of complex DNA strings causes wear, while simpler or specifically designed 'maintenance' strings can restore integrity.

## The Tradeoff

- **What the player wants**: To process high-density DNA (low scarcity TEX) for maximum data/utility.
- **What the world demands**: The system has finite endurance. Overuse leads to failure.
- **Consequences**:
    - Processing high-density DNA (TEX scarcity < 2000) drains integrity rapidly (-5).
    - Standard processing drains integrity (-2).
    - If integrity reaches 0, the system refuses to process any DNA except maintenance DNA.
- **Skillful Play**: Balancing high-value/high-wear processing with periodic maintenance runs (TEX scarcity > 8000) to keep the system operational.

## Deterministic Rules

1.  **High-Stress DNA**: `TEX` with `scarcity` < 2000 drains **5** integrity units.
2.  **Maintenance DNA**: `TEX` with `scarcity` > 8000 restores **10** integrity units (capped at 100).
3.  **Standard DNA**: All other successful parses drain **2** integrity units.
4.  **Refusal**: When integrity is 0, only **Maintenance DNA** is processed. All others are skipped (not recorded in ledger, allowing retry).
5.  **Persistence**: Integrity state is saved atomically in `data/system_integrity.json`.

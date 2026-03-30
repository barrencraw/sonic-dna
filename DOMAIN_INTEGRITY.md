# Domain: System Integrity & Fatigue

## Pressure Axis: Fatigue / System Degradation

### The Tradeoff
- **What the player wants:** To process high-density DNA strings (low scarcity) for maximum data output.
- **What the world demands:** Each processing operation induces "system wear." High-density operations (TEX scarcity < 2000) are particularly taxing.
- **The Consequence:** If System Integrity hits 0, the processor refuses all non-maintenance tasks.
- **Skillful Play:** Balancing high-yield operations with "Maintenance DNA" (TEX scarcity > 8000) to restore integrity.

### Mechanics (Deterministic)
- **Standard Wear:** -2 integrity units per DNA string.
- **High-Density Wear:** -5 integrity units for TEX strings with scarcity < 2000.
- **Maintenance Restore:** +10 integrity units for TEX strings with scarcity > 8000 (Capped at 100).
- **Refusal Boundary:** At 0 integrity, only Maintenance DNA is processed. All others return a `REFUSAL` outcome and are not added to the ledger (allowing retry after maintenance).

### Legibility (Indifferent Tone)
- **Consequence Applied:** `SYSTEM_WEAR: {wear} units. CURRENT_INTEGRITY: {integrity}.`
- **Refusal Reason:** `INTEGRITY_LEVEL_CRITICAL: Non-maintenance processing suspended.`
- **Next Action Hint:** `Execute Maintenance DNA (TEX scarcity > 8000) to restore integrity.`

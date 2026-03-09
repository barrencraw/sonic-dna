# System Integrity Mechanic

The SonicDNA processing engine is a physical system with finite durability. High-complexity operations cause wear, while low-density maintenance strings allow for recalibration.

## Pressure Axis: Fatigue

The "Fatigue" axis represents the mechanical and computational strain on the DNA processing pipeline. Processing dense, highly varied DNA structures rapidly depletes the system's operational integrity.

## The Tradeoff

### What the Player Wants
To process high-complexity, high-variation DNA (TEX with high layering and variation) to generate rich, evolving sonic textures.

### What the World Demands
Mechanical stability. The system is not designed for continuous high-load operations.

### Consequences
- **Processing High-Complexity DNA:** TEX strings with `layering > 500` or `variation > 7000` drain **10 units** of System Integrity.
- **Maintenance:** TEX strings with `scarcity > 9000` (sparse events) restore **5 units** of System Integrity.
- **Refusal:** If System Integrity reaches **0**, all non-maintenance DNA processing is refused.

### Skillful Play
Managing the processing queue to alternate between "heavy" complexity strings and "light" maintenance strings to keep integrity above zero without halting operations.

## UI Legibility (Indifferent Tone)

- **Consequence Applied:** `[SYSTEM] OPERATIONAL WEAR DETECTED. INTEGRITY ADJUSTED.`
- **Refusal Reason:** `[CRITICAL] SYSTEM INTEGRITY DEPLETED. NON-MAINTENANCE TASKS HALTED.`
- **Next Action Hint:** `[INFO] EXECUTE MAINTENANCE SEQUENCE (HIGH SCARCITY DNA) TO RESTORE FUNCTIONALITY.`

## Implementation
Managed by `utils/integrity_manager.py` and integrated into the `dna_ui.py` batch processor. State is persisted in `data/system_integrity.json`.

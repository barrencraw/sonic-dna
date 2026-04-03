# Domain: Fatigue & System Integrity

## The Pressure Axis: Fatigue / Wear

The SonicDNA processing engine is no longer an infinite, costless resource. Every operation exerts "wear" on the underlying system integrity. If integrity reaches zero, the system refuses to process new DNA (except for maintenance strings).

## The Tradeoff

- **What the player wants:** To parse as many DNA strings as possible to build their generative dataset.
- **What the world demands:** Conservation of system resources and periodic maintenance.
- **What gets worse:**
    - **Choose A (Continuous Parsing):** System integrity drains. High-complexity textures (low scarcity) drain it faster. Eventually, the system locks up.
    - **Choose B (Maintenance):** Player must find or generate "Maintenance DNA" (specifically defined as TEX strings with high scarcity / low density). This costs time/input slots but restores integrity.
- **Skillful Play:** Batching high-wear DNA with maintenance strings to keep the system above the refusal threshold without hitting 0 mid-batch.

## The Rules

1.  **System Integrity:** A value from 0 to 100, stored in `data/system_integrity.json`.
2.  **Wear Application:**
    - Every successful DNA parse reduces integrity.
    - **Normal Wear:** -2 integrity.
    - **Heavy Load (TEX scarcity > 8000):** -5 integrity. (Wait, scarcity 10000 is isolated/empty. Density 0 is full. Let's say high *density* is high wear).
    - Correction: **Heavy Load (TEX scarcity < 2000):** -5 integrity (Dense textures are harder to parse).
3.  **Maintenance:**
    - A DNA string is considered "Maintenance" if it is a **TEX** rule and **scarcity > 9000** (very sparse).
    - Processing Maintenance DNA restores **+10 integrity** (capped at 100).
    - Maintenance DNA is *never* refused, even at 0 integrity.
4.  **Refusal:**
    - If integrity is **0**, any non-maintenance DNA parse request is returned as a **REFUSAL**.
    - Refused DNA is NOT added to the persistent ledger, allowing it to be retried later.

## Determinism
- Wear is subtracted/added exactly as defined. No RNG.
- The state is persisted atomically alongside the ledger.

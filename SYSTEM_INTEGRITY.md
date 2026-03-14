# System Integrity Mechanic

## Overview
System Integrity represents the operational wear of the DNA processing engine. High-complexity DNA strings cause physical strain on the synthesis hardware, while specific maintenance strings are required to recalibrate and restore stability.

## Pressure Axis: Fatigue & Maintenance
The player is incentivized to push for maximum complexity (high layering, high variation), but doing so depletes a finite resource: **Integrity**.

### Tradeoffs
*   **The Player Wants:** Ultra-dense, rapidly varying textures (high `layering`, high `variation`) for maximum sonic density.
*   **The World Demands:** Structural stability. Overworking the system leads to refusal.
*   **What Gets Worse:**
    *   Choosing high complexity drains 10 units of Integrity.
    *   At 0 Integrity, the system refuses to process any non-maintenance DNA.
*   **Skillful Play:** Balancing high-output sessions with "cooldown" periods using high-scarcity maintenance strings (`scarcity` > 9000) that restore 5 units of Integrity.

## Deterministic Rules
1.  **Drain:** If `Texture Complexity` DNA has `layering > 500` OR `variation > 7000`, Integrity decreases by 10.
2.  **Restore:** If `Texture Complexity` DNA has `scarcity > 9000`, Integrity increases by 5 (capped at 100).
3.  **Refusal:** If Integrity is 0, only maintenance strings are accepted. All other DNA returns a `REFUSAL` outcome.

## UI Feedback (Indifferent Tone)
*   **Consequence Applied:** "System wear increased. Structural integrity compromised."
*   **Refusal Reason:** "Critical integrity failure. Non-essential processing suspended."
*   **Next Action Hint:** "Execute high-scarcity maintenance strings to restore stability."

## Implementation Details
*   State persisted in `data/system_integrity.json`.
*   Atomic updates alongside the processed ledger to ensure idempotency.
*   Messages managed via `data/system_messages.json`.

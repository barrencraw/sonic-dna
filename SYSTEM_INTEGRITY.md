# System Integrity Mechanic

## Overview
System Integrity represents the structural stability of the synthesis engine. High-complexity operations strain the system, while specialized maintenance strings restore stability. This is a "you don't matter" mechanic—the world demands balance, or it fails.

## Mechanics
- **Base Integrity:** 100 (Maximum)
- **Minimum Integrity:** 0
- **Drain Rule:** If a "Texture Complexity" (TEX) DNA string has `layering > 500` or `variation > 7000`, integrity is reduced by **10 units**.
- **Restore Rule:** If a "Texture Complexity" (TEX) DNA string has `scarcity > 9000`, integrity is increased by **5 units** (up to 100).
- **Deterministic:** No RNG. Consequence is applied immediately upon successful parsing.
- **Idempotency:** Re-processing the same DNA string (deduplication) does not apply consequences multiple times.

## UI Feedback (Indifferent Tone)
- **Consequence Applied:** "System integrity adjusted. Operation within expected parameters."
- **Refusal Reason:** "Process halted. Integrity levels insufficient to maintain coherence."
- **Next Action Hint:** "Input maintenance strings (scarcity > 9000) or reduce complexity to stabilize."

## Tradeoff
- **Player Desire:** High-density, highly-variable textures.
- **World Demand:** Structural coherence.
- **Consequence:** Pushing complexity without maintenance will lead to system degradation and eventual refusal of service.
- **Skillful Play:** Balancing complex textural generations with periodic maintenance strings to keep the system in the "green" zone.

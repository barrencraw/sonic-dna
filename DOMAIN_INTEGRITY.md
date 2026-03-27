# Domain Integrity: Fatigue Mechanic

## Pressure Axis: Fatigue / System Integrity

### Design Tradeoff
*   **What the player wants:** To process as much DNA as possible to gain insights/data.
*   **What the world demands:** Systems wear down with use. Maintenance is required to keep the processing chain operational.
*   **A vs B Choice:**
    *   **A (Processing):** Gain data, but drain system integrity. Normal DNA drains 2 units. High-complexity/Low-scarcity DNA (TEX < 2000) drains 5 units due to stress.
    *   **B (Maintenance):** Process specific "Maintenance DNA" (TEX > 8000) to restore 10 units of integrity. This consumes a processing slot but keeps the system alive.
*   **Skillful Play:** Balancing the processing of valuable but high-wear DNA with timely maintenance DNA to avoid a total system refusal (Integrity = 0).

### UI Messages (Indifferent Tone)
*   **Consequence Applied:** System integrity adjusted. The world remains indifferent.
*   **Refusal Reason:** System integrity critical. Processing halted.
*   **Next Action Hint:** Provide maintenance DNA or await manual intervention.

### Deterministic Rules
1.  **Wear Calculation:**
    *   `Texture Complexity` with `scarcity < 2000`: -5 Integrity.
    *   `Texture Complexity` with `scarcity > 8000`: +10 Integrity (capped at 100).
    *   All other DNA types: -2 Integrity.
2.  **Refusal Condition:**
    *   If `Integrity == 0`, all non-maintenance DNA processing is refused.
    *   Maintenance DNA (TEX > 8000) can still be processed to restore integrity.

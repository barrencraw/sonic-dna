# Domain: System Integrity (Fatigue Axis)

## Objective
Increase consequence density by introducing a finite resource (Integrity) that is consumed by complex operations and restored by maintenance tasks.

## The Tradeoff
- **What the player wants:** To process high-complexity DNA (Texture Complexity) to unlock advanced features or higher-quality outputs.
- **What the world demands:** Systems wear out. Continuous high-load processing leads to failure without periodic maintenance.
- **Consequences:**
    - Choosing **high-complexity processing (A)** drains integrity rapidly. If integrity hits 0, the system refuses further work.
    - Choosing **maintenance processing (B)** restores integrity but produces no usable domain output, consuming time and resources.
- **Skillful Play:** Balancing high-yield, high-wear runs with just enough maintenance to keep the system operational, avoiding the "refusal" state which blocks all progress.

## Mechanic Rules (Deterministic)
Integrity starts at 100, capped at 100.

| Operation | Condition | Consequence |
| :--- | :--- | :--- |
| **High Wear** | TEX Scarcity < 2000 | -5 Integrity |
| **Standard Wear** | All other processing (except maintenance) | -2 Integrity |
| **Maintenance** | TEX Scarcity > 8000 | +10 Integrity (cap 100) |

### Refusal Logic
- If Integrity == 0:
    - All non-maintenance DNA processing is **REFUSED**.
    - Outcome is recorded as `REFUSAL`.
    - Maintenance DNA is **always allowed**, even at 0 Integrity.

## Legibility
- **Consequence Applied:** Recorded in structured logs as `consequence_applied`.
- **Refusal Reason:** Logged when processing is blocked due to 0 integrity.
- **Next Action Hint:** Indifferent guidance on how to restore system function.

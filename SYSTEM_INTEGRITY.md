# System Integrity Mechanic

## Pressure Axis: Fatigue / System Risk

### Design: The Tradeoff

- **What the player wants:** To process complex and rich "Texture Complexity" (TEX) DNA to generate high-fidelity audio structures.
- **What the world demands:** The processing engine is ancient and fragile. High-complexity operations (high layering, high variation) create thermal and structural stress.
- **Consequences:**
  - **A (Complex Processing):** Choosing to process complex TEX DNA (layering > 500 or variation > 7000) drains **System Integrity** by 10 units. If integrity reaches 0, the system refuses to process further complex strings.
  - **B (Maintenance):** Choosing to process high-scarcity "maintenance" strings (scarcity > 9000) restores **System Integrity** by 5 units but produces minimal/silent audio output.
- **Skillful Play:** The player must monitor the `system_integrity.json` level and weave in low-complexity maintenance strings between bursts of high-intensity creative work. Failure to do so leads to hard lockouts from the most powerful tools.

### Invariants
1. System Integrity starts at 100.
2. Minimum integrity is 0. Maximum integrity is 100.
3. Integrity changes are idempotent (only applied once per unique DNA string processed).

### UI Messaging (Indifferent Tone)
- **Consequence Applied:** "System integrity adjusted: {change} units. Current level: {total}."
- **Refusal Reason:** "System integrity insufficient. Processing aborted."
- **Next Action Hint:** "Execute maintenance strings (Scarcity > 9000) to stabilize."

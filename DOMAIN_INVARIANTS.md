# Domain Invariants

## Fatigue Axis: System Integrity

The DNA processing system is not an infinite resource. It is subject to physical wear and tear, represented by the **System Integrity** metric.

### State
- **System Integrity**: An integer value between 0 and 100.
- **Persistence**: Stored in `data/system_integrity.json`.

### Transitions (Deterministic Wear)
- **Standard Wear**: Every DNA string processed (successful or error) drains **2** integrity units by default.
- **High-Complexity Drain**: DNA strings of type `Texture Complexity` (TEX) with a `scarcity` value less than **2000** are particularly taxing, draining **5** integrity units.
- **Maintenance Restoration**: DNA strings of type `Texture Complexity` (TEX) with a `scarcity` value greater than **8000** are considered "maintenance" strings. They restore **10** integrity units, up to the maximum of 100.

### The Refusal Rule
- If System Integrity is **0**, the system will refuse to process any DNA strings unless they are **Maintenance Restoration** strings.
- Non-maintenance strings submitted while at 0 integrity will result in a `REFUSAL` outcome.
- Refused strings are **not** recorded in the idempotency ledger, allowing them to be retried once the system is repaired.

### Skillful Play
Players must monitor the system's "fatigue" and periodically intersperse their high-value, complex DNA processing with maintenance strings to keep the system operational. Ignoring integrity leads to total system lockout, forcing a dedicated maintenance phase.

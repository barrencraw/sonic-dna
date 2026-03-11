# System Integrity Mechanic

## Tradeoff Design

| Element | Description |
| :--- | :--- |
| **Player Want** | High-complexity audio (dense layering, high variation). |
| **World Demand** | System stability; processing complex DNA causes operational wear. |
| **Consequence (A vs B)** | Choosing high complexity (A) drains System Integrity. Choosing high scarcity (B) restores it but yields minimal audio content. |
| **Skillful Play** | Balancing high-output sessions with "maintenance" runs (high-scarcity DNA) to keep the system operational without hitting a total refusal state. |

## Rules

- **Initial State**: 100 Integrity.
- **Drain**: Texture Complexity (TEX) DNA with `layering > 500` OR `variation > 7000` drains **10 integrity**.
- **Restore**: Texture Complexity (TEX) DNA with `scarcity > 9000` (maintenance string) restores **5 integrity** (capped at 100).
- **Refusal**: If integrity is **0**, all non-maintenance DNA processing is refused with a `REFUSAL` outcome.

## Legibility (World-Building)

The system communicates consequences and refusals with an indifferent, informative tone:

- **Consequence Applied**: `Operational wear detected. System integrity recalibrated.`
- **Refusal Reason**: `System integrity at critical minimum. Non-maintenance processing suspended.`
- **Next Action Hint**: `Submit high-scarcity maintenance DNA to restore operational capacity.`

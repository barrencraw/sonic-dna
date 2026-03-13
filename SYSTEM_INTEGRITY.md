# System Integrity Mechanic

SonicDNA implements a Fatigue/System Integrity mechanic to simulate operational wear and the indifference of the system towards excessive complexity.

## The Tradeoff

- **What you want**: High-complexity audio with dense layering and extreme variation.
- **What the world demands**: System stability.
- **The Consequence**: Processing "Heavy" DNA strings drains System Integrity.

## Rules

Integrity is a value between **0** and **100**.

### Integrity Drain (Wear)
Processing a `Texture Complexity` (TEX) DNA string with any of the following triggers a **-10** integrity drain:
- **Layering > 500**: Ultra-dense multi-layered textures.
- **Variation > 7000**: High internal variation index.

### Integrity Restore (Maintenance)
Processing a `Texture Complexity` (TEX) DNA string with:
- **Scarcity > 9000**: Absolute scarcity / isolated events.
Triggers a **+5** integrity restoration.

## System Refusal

If System Integrity reaches **0**, the system enters **Operational Failure** mode.
- All non-maintenance DNA strings (those that don't restore integrity) will be **REFUSED**.
- The system will only accept high-scarcity "Maintenance" strings until integrity is restored above 0.

## Legibility

- **Consequence Applied**: `Wear detected. Complexity threshold exceeded.`
- **Refusal Reason**: `Integrity 0. Operational failure.`
- **Next Action Hint**: `Restore required. Input high-scarcity DNA.`

## Skillful Play

Maintain system health by interleaving complex generative tasks with "breather" maintenance cycles. Blindly pushing for maximum complexity will lead to system lockout.

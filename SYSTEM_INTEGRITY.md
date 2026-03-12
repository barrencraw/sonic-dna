# System Integrity / Fatigue Mechanic

## Overview
The system tracks operational wear via a `System Integrity` metric (0-100). High-complexity DNA processing operations cause system strain, while specific maintenance-oriented DNA can restore integrity.

## The Pressure Axis: Fatigue
As the system processes increasingly complex DNA, it accumulates wear. This is not a narrative choice, but a systemic constraint on throughput.

## The Tradeoff
- **Creative Goal:** The player wants high-density, highly variable textures (High Layering, High Variation) for maximum sonic richness.
- **Systemic Demand:** The hardware requires cooling and recalibration. Overloading it leads to operational refusal.
- **Consequence A (Creative Push):** Processing dense DNA (`layering > 500` or `variation > 7000`) drains **10 integrity**.
- **Consequence B (Maintenance):** Processing high-scarcity DNA (`scarcity > 9000`) restores **5 integrity** but produces "thin" or "empty" sonic results.
- **Refusal:** When integrity reaches **0**, all non-maintenance DNA strings are rejected with a `REFUSAL` outcome.

## Skillful Play
Skillful play involves interleaving "maintenance" DNA strings into a batch to offset the drain of complex textures, ensuring the system never hits a hard refusal state while maintaining the highest possible average output complexity.

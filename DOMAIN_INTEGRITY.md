# Domain Integrity: Fatigue Mechanic

## Pressure Axis: Fatigue
The system's integrity represents its operational health. Processing DNA strings causes wear on the system. If integrity drops to zero, the system enters a state of refusal for non-maintenance tasks.

## Tradeoff Design
- **What the player wants:** To process complex DNA strings for maximum information/results.
- **What the world demands:** Periodic maintenance to keep the system operational.
- **Consequences:**
  - Choosing **High-Complexity Processing** (A): Fast results, but rapid integrity drain (-5).
  - Choosing **Maintenance** (B): No immediate results, but restores integrity (+10).
  - **Standard Processing**: Moderate results, steady wear (-2).

## Deterministic Rule Set
- **High-Complexity (Drain 5):** Any DNA string matching `Texture Complexity` (TEX) where `scarcity < 2000`.
- **Maintenance (Restore 10):** Any DNA string matching `Texture Complexity` (TEX) where `scarcity > 8000`.
- **Standard (Drain 2):** All other DNA processing events.
- **Maximum Integrity:** 100.
- **Minimum Integrity:** 0.

## Refusal Logic
- At **0 integrity**, the system will refuse to process any DNA string unless it is a **Maintenance** string.
- Maintenance strings bypass refusal and restore integrity.

## Skillful Play
Skillful play involves monitoring integrity levels and strategically interleaving maintenance DNA into the processing queue to prevent system downtime. It's about efficiency versus sustainability.

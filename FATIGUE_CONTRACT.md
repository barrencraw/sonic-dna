# Thermal Fatigue System Contract

## Pressure Axis
Fatigue (Thermal Stress)

## Tradeoff
- **Player Wants:** High-throughput processing of high-amplitude (VOL) DNA sequences.
- **World Demands:** Hardware thermal limits must be respected.
- **Consequences:**
    - **Choice A (Aggressive):** Rapid processing leads to heat accumulation. Beyond 5.0 units, "Thermal Noise" scales numeric outputs by 0.9. Beyond 10.0 units, "Thermal Overload" causes a fatal refusal.
    - **Choice B (Conservative):** Low-amplitude sequences or waiting allows heat to dissipate (-0.5 per batch), maintaining high signal-to-noise ratio.
- **Skillful Play:** Interleaving high-intensity bursts with low-intensity "cooling" sequences or strategic downtime.

## UI Message Keys
- **Consequence Applied:** `[SYSTEM] Thermal noise active... (Output scaled by 0.9)`
- **Refusal Reason:** `[FATAL] Thermal Overload: Hardware protection engaged.`
- **Next Action Hint:** `[INFO] Dissipate heat via low-amplitude cycles or wait for passive cooling.`

## Mechanics
- **Base Dissipation:** -0.5 heat per `main()` execution (batch).
- **Heat Gain (VOL):** `0.1 + (amp / 500.0)`
- **Thermal Noise Threshold:** > 5.0 heat.
- **Thermal Overload Threshold:** > 10.0 heat.

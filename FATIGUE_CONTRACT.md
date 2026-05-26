# Thermal Fatigue System Contract

## Pressure Axis: Fatigue (Thermal)

The DNA Processing Core generates heat during operation. Excessive throughput without dissipation leads to hardware instability and eventual refusal.

## The Tradeoff

*   **What the player wants:** Maximum throughput; processing large batches of DNA strings quickly.
*   **What the world demands:** Hardware integrity; cooling cycles and dissipation time.
*   **What gets worse:**
    *   **Choice A (High Speed):** Persistent high heat (> 5.0) causes **Thermal Noise**, degrading output fidelity (numeric values scaled by 0.9).
    *   **Choice B (Stability):** Slower throughput due to intentional cooling cycles or idle time to dissipate heat.
*   **Skillful Play:** Interspersing low-amplitude `VOL` sequences (cooling cycles) to maintain heat below the noise threshold (5.0) while maximizing progress.

## Systemic Rules

1.  **Heat Accumulation:**
    *   Only `Volume` (VOL) DNA strings currently affect system heat.
    *   Gain Formula: `0.1 + (amp / 500.0)` per sequence.
2.  **Cooling Cycles:**
    *   `Volume` (VOL) sequences with `amp < 100` act as cooling cycles.
    *   Cooling Effect: `-0.5` per sequence (clamped at 0.0).
3.  **Passive Dissipation:**
    *   The system dissipates `0.1` heat at the start of every batch processing run, provided at least one DNA sequence is processed.
4.  **Thermal Noise (Consequence):**
    *   Threshold: Heat > 5.0.
    *   Effect: All numeric leaf values in the parsed output (excluding booleans) are multiplied by `0.9`.
5.  **Thermal Overload (Refusal):**
    *   Threshold: Heat > 10.0.
    *   Effect: The system raises `ThermalOverloadError` and terminates the current batch immediately. Progress made before the overload is preserved.

## UI Message Keys (Indifferent Tone)

*   **Consequence Applied:** `[WARN] Thermal Noise detected. Fidelity degradation active.`
*   **Refusal Reason:** `[FATAL] Thermal Overload. Core temperature exceeding safety limits.`
*   **Next Action Hint:** `[INFO] Dissipate heat. Cooling cycles required.`

## Determinism
No RNG. Thermal gain, noise application, and dissipation are deterministic calculations based on DNA sequence parameters and current state.

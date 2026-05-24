# Thermal Fatigue System Contract

## Pressure Axis: Fatigue (Thermal)

### Tradeoff
- **What the player wants:** Maximum throughput; processing large batches of DNA sequences rapidly.
- **What the world demands:** Hardware integrity; the processing core accumulates heat based on the energy required for synthesis.
- **What gets worse:**
  - **Threshold A (> 5.0 heat):** **Thermal Noise.** Numeric outputs are scaled by 0.9x, introducing deterministic fidelity loss.
  - **Threshold B (> 10.0 heat):** **Thermal Overload.** The system refuses further processing to prevent hardware failure.
- **Skillful Play:**
  - Monitoring `system_heat` via logs/UI.
  - Interleaving high-amplitude sequences with "Cooling Cycles" (Low-amplitude VOL sequences).
  - Managing batch sizes to allow for passive dissipation.

### Deterministic Rules
1. **Heat Accumulation (VOL sequences):**
   - Base gain: `0.1` per sequence.
   - Amplitude gain: `amp / 500.0`.
   - *Example:* A VOL sequence with `amp=890` adds `0.1 + 1.78 = 1.88` heat.
2. **Cooling Cycles:**
   - Any `VOL` sequence with `amp < 100` (e.g. `0090`) acts as a cooling cycle.
   - Effect: `-0.5` heat (instead of gain).
3. **Passive Dissipation:**
   - Every batch run (if the input list is not empty) reduces total `system_heat` by `0.1`.
4. **Thermal Noise (The Consequence):**
   - If `system_heat > 5.0` when processing a sequence, all numeric leaf values in the parsed result are multiplied by `0.9`.
5. **Thermal Overload (The Refusal):**
   - If `system_heat + projected_gain > 10.0`, the system raises `ThermalOverloadError`.
   - Current item is NOT processed. Previous items in the same batch remain committed.

### UI Message Keys
- **Consequence Applied:** `[WARN] Thermal Noise detected. Fidelity degradation active.`
- **Refusal Reason:** `[FATAL] Thermal Overload. Core temperature exceeding safety limits.`
- **Next Action Hint:** `[INFO] Dissipate heat. Cooling cycles required.`

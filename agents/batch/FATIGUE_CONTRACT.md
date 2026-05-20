# Thermal Fatigue Contract

## Context
The DNA Parser hardware is an aging, overclocked unit in a high-entropy environment. Processing DNA sequences generates thermal waste.

## The Tradeoff
- **Player Desire**: High-throughput processing of complex, high-amplitude DNA.
- **World Demand**: Hardware thermal integrity must be maintained.
- **A vs B**:
    - **A (Aggressive)**: Process high-amplitude sequences. Result: Fast completion, but rapid heat build-up leading to "Thermal Noise" (distorted output) and eventually "Thermal Overload" (refusal to work).
    - **B (Conservative)**: Process low-amplitude sequences or wait. Result: Heat dissipates, maintaining output precision.

## Systemic Rule: Thermal Fatigue
1. **Heat Accumulation**:
    - Every successfully parsed `Volume` (VOL) sequence adds heat: `0.1 + (amp / 500.0)`.
    - Every other sequence adds a flat `0.2` heat.
    - Heat is persistent across batches in `data/system_state.json`.
2. **Thermal Noise (Threshold: 5.0)**:
    - If `current_heat + heat_gain > 5.0`, the system applies "Thermal Noise".
    - All numeric values in the parsed leaf nodes are multiplied by `0.9` (precision loss).
3. **Thermal Overload (Threshold: 10.0)**:
    - If `current_heat + heat_gain > 10.0`, the system raises `ThermalOverloadError`.
    - The batch is aborted; no further sequences are processed.
4. **Dissipation**:
    - Each sequence processed (even if skipped by idempotency) allows for a tiny bit of passive cooling? No, let's keep it simple: Heat only goes up during processing and needs "cooling cycles" (low amp) to go down?
    - Actually, let's make it: Sequences with `amp < 100` dissipate `0.5` heat instead of adding.
    - "Passive Dissipation": Every time `dna_ui.main()` is called, heat decreases by `1.0` (simulating time passed between batches).

## Legibility (UI Messages)
- **Consequence Applied**: `[SYSTEM] Thermal noise active. Precision loss detected.`
- **Refusal Reason**: `[FATAL] Thermal Overload. Cooling required.`
- **Next Action Hint**: `[INFO] Dissipate heat via low-amplitude cycles or wait.`

## Determinism
- No RNG. All heat calculations and noise multipliers are fixed.
- Heat state is visible/stored in `data/system_state.json`.

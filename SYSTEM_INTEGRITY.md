# System Integrity Mechanic

## Overview
The System Integrity mechanic represents the physical and computational strain of synthesizing complex audio textures. It is a deterministic system that forces a tradeoff between output complexity and core stability.

## Pressure Axis: Fatigue / Scarcity
- **The Player Wants:** High-density, varied textural synthesis (Texture Complexity DNA).
- **The World Demands:** Core stability maintenance.
- **Tradeoff:** Processing high-complexity strings drains system integrity. Once integrity is depleted, the core enters a lockdown state and refuses to process anything except low-density "maintenance" strings.

## Rules
- **Initial Integrity:** 100%
- **Drain:** Any `Texture Complexity` (TEX) DNA string with `layering > 500` or `variation > 7000` drains **10 units** of integrity.
- **Restore:** Any `Texture Complexity` (TEX) DNA string with `scarcity > 9000` restores **5 units** of integrity.
- **Refusal:** At **0% integrity**, only maintenance strings (`scarcity > 9000`) are accepted. All other processing is refused.

## Implementation
- **State:** Persisted in `data/system_integrity.json`.
- **Logic:** Handled by `utils/integrity_manager.py` and integrated into the `utils/dna_ui.py` pipeline.
- **Atomicity:** Integrity state is updated as part of the atomic commit pattern alongside results and the idempotency ledger.
- **Observability:** System messages and status changes are logged with the `[OBSERVABILITY]` prefix using keys from `data/system_messages.json`.

## Skillful Play
Players must balance the synthesis of high-value complex textures with periodic "low-load" maintenance cycles. Blindly pushing complexity leads to downtime, while careful rotation ensures continuous operation.

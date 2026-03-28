# Domain: System Integrity (Fatigue)

## Design Tradeoff
- **Player Wants**: To process as many DNA strings as possible to build their dataset/synthesizer.
- **World Demands**: Every operation puts wear on the system. High-density textures cause significant drain.
- **Consequences**:
    - **A (High Intensity)**: Processing complex textures (TEX Scarcity < 2000) drains integrity rapidly (-5).
    - **B (Maintenance)**: Restoring the system requires processing 'sparse' Texture Complexity DNA (TEX Scarcity > 8000), which adds +10 integrity but yields little useful 'dense' data.
- **Skillful Play**: Balancing the throughput of high-value dense DNA with timely maintenance runs to avoid total system refusal.

## Mechanics
- **Integrity Range**: 0 to 100.
- **Wear Rules**:
    - **TEX Scarcity < 2000**: -5 integrity.
    - **TEX Scarcity > 8000 (Maintenance)**: +10 integrity (capped at 100).
    - **Standard Operation**: -2 integrity for all other DNA processing.
- **Refusal**: If integrity is 0, the system returns a `REFUSAL` outcome for any non-maintenance DNA. `REFUSAL` states are NOT recorded in the idempotency ledger, allowing them to be retried once the system is restored.

## Observability
- Logs include `system_msg` (consequence/refusal info) and `latency_ms`.
- System integrity state is persisted atomically in `data/system_integrity.json`.

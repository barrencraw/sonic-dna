# System Integrity & Fatigue Domain

## Fatigue Mechanic
The system integrity mechanic represents the operational health of the DNA processing chain. Each non-maintenance DNA processing event applies "wear" to the system, reducing its integrity.

## Wear Rules
- **Non-Maintenance DNA**:
    - **Success**: Integrity -5.
    - **Error**: Integrity -2.
- **Maintenance DNA**:
    - **Restoration**: Integrity +10 (max 100).
    - **Bypass**: Maintenance DNA can be processed even when integrity is 0.

## Maintenance DNA Definition
DNA is considered maintenance DNA if it corresponds to the `Texture Complexity` rule (prefix `TEX`) and its `scarcity` value is greater than 8000.

## Refusal Condition
When system integrity reaches 0, non-maintenance DNA processing is halted, returning a `REFUSAL` outcome. `REFUSAL` outcomes are not recorded in the ledger to allow future retries once maintenance is performed.

## State Durability
System integrity is stored in `data/system_integrity.json` and must be updated atomically alongside the processing results and the ledger.

## UI Response
When integrity is low or a refusal occurs, the UI and observability logs must include indifferent, informative messages defined in `data/system_messages.json`.

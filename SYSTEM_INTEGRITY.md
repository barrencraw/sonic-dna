# System Integrity Mechanic

## Pressure Axis: Fatigue / System Integrity
The system is not an infinite resource. Processing complex DNA structures places a measurable strain on the underlying fabric. This strain is represented by **System Integrity**.

## The Tradeoff: Complexity vs. Maintenance

### 1. What the player wants
Players want to generate rich, dense, and evolving audio textures. In terms of `Texture Complexity` (TEX) DNA, this means:
- High **layering** (> 500): Many simultaneous independent textural streams.
- High **internal variation** (> 7000): Non-repeating, complex microstructure.

### 2. What the world demands
The world demands stability and periodic maintenance. It rewards "quiet" or "sparse" operations that allow the system to recalibrate.
- High **scarcity** (> 9000): Isolated events or near-silence.

### 3. Consequence Applied
- **Drain:** Processing a TEX DNA string with `layering > 500` OR `variation > 7000` drains **10 units** of System Integrity.
- **Restore:** Processing a TEX DNA string with `scarcity > 9000` restores **5 units** of System Integrity (up to a maximum of 100).
- **Refusal:** If System Integrity reaches **0**, the system refuses to process any non-maintenance DNA strings (those that do not meet the restore criteria).

### 4. Skillful Play
Skillful play involves interleaving complex, resource-heavy textural requests with sparse maintenance strings. An indifferent system will not warn you until it stops working; it is your responsibility to monitor the "fatigue" of the sequence.

## UI Message Keys (data/system_messages.json)
- `consequence_applied`: "System integrity depleted by 10 units due to complexity overhead."
- `refusal_reason`: "Integrity at zero. Non-maintenance DNA rejected."
- `next_action_hint`: "Submit high-scarcity (maintenance) DNA to restore system stability."

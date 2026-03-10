# System Integrity (Fatigue)

## Pressure Axis: Operational Wear (Fatigue)
The processing unit is not an infinite resource. Each DNA string processed exerts a physical toll on the system's hardware substrates.

## Tradeoff: Complexity vs. Maintenance
- **High Complexity**: DNA strings with Texture Complexity (TEX) values of `layering > 500` or `variation > 7000` demand excessive compute cycles and thermal overhead.
- **Maintenance**: DNA strings with Texture Complexity (TEX) `scarcity > 9000` are recognized as low-entropy "rest" states that allow the system to recalibrate.

### The Consequences
- **Processing High Complexity DNA**: Reduces System Integrity by **10 units**.
- **Processing Maintenance DNA**: Restores System Integrity by **5 units**.
- **The Limit**: If System Integrity reaches **0**, the system enters a fail-safe state.
- **Fail-safe Behavior**: The system will **REFUSE** to process any non-maintenance DNA strings. Only maintenance strings (Scarcity > 9000) will be accepted until integrity is restored above 0.

### Skillful Play
Players must monitor their batch composition. Including high-scarcity maintenance strings within a batch of complex DNA allows for sustained operation without hitting the hard refusal limit.

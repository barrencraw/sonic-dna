# Volatility Risk & Acoustic Saturation System

### Pressure Axis: Risk

In SonicDNA, processing high-fidelity acoustic variables at rapid frequencies destabilizes the synthesizer's mainframe buffer. This introduces high-frequency interference, quantified as **System Volatility**.

### Tradeoff Design
* **What the player wants**: The player wants to extract maximum acoustic detail from each DNA sequence. High-fidelity sequences (ending with the `_HF` modifier) yield deep spectral parameters but accumulate extreme system volatility.
* **What the world demands**: Mainframe thermal and magnetic alignment. The system cannot sustain operations under extreme high-frequency resonance.
* **A vs B Consequence**:
  * **Choice A (High Fidelity)**: Processing high-fidelity sequences or heavy normal batch sequences increases volatility rapidly (+3.0 for `_HF` and +1.0 for normal). If volatility reaches or exceeds the threshold of **10.0**, the compiler triggers a safety lockout, refusing further operations. Sub-variables of subsequent items remain unparsed and locked.
  * **Choice B (Stabilization / Waiting)**: Players can run a `STABILIZE` cycle to lower volatility (-4.0 immediately) or wait for real-time dissipation (decay of 0.2 units per second). However, this takes time and introduces processing delays.
* **Skillful Play**: Interleaving high-fidelity sequences with stabilization cycles or scheduled idle cooldown periods to keep system volatility just below 10.0, thereby squeezing maximum throughput out of the compiler without triggering a lockout.

### UI / Systemic Message Keys
* **Consequence Applied**: `"Acoustic Saturation Accumulation"`
  * *Description*: System Volatility increased.
* **Refusal Reason**: `"Acoustic Saturation Lockout"`
  * *Description*: Volatility threshold (10.0) exceeded. Core parsing blocked.
* **Next Action Hint**: `"Wait for dissipation or run STABILIZE. The system is indifferent to your deadlines."`
  * *Description*: Relentless, informative, indifferent hint motivating the next steps.

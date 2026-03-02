# Determinism Surface Map

## RNG
- **Source:** `numpy.random`
- **Citations:**
  - `ui/music_panel.py:83`: `np.random.uniform` (Sample & Hold)
  - `ui/music_panel.py:89`: `np.random.uniform` (Stepped Random)
  - `ui/music_panel.py:93`: `np.random.uniform` (White Noise)
  - `ui/music_panel.py:98`: `np.random.randn` (Pink Noise)
  - `ui/music_panel.py:104`: `np.random.uniform` (Brown Noise)
  - `ui/music_panel.py:111`: `np.random.normal` (Blue Noise)
  - `ui/music_panel.py:118`: `np.random.normal` (Violet Noise)
  - `ui/music_panel.py:125`: `np.random.normal` (Grey Noise)
- **Impacted Entry Points:** `gen_wave()`, `MusicPanel.update_waveform()`
- **Current Injection:** None (Direct global calls)
- **Flakiness Risk:** **High**. Every call to generate random-based waveforms produces different data.
- **Recommended Provider:** `RngProvider` (wrapping `numpy.random.Generator`)

## Time
- **Source:** `time`
- **Citations:**
  - `main.py:86, 96`: `time.strftime`
  - `main.py:103`: `time.sleep`
  - `utils/lmstudio_tool.py:38`: `time.sleep`
  - `agents/batch/sequence.py:35, 96`: `time.sleep`
- **Impacted Entry Points:** `watch_loop()`, `LMStudioTool.ask()`, `wait_for_lm_studio()`
- **Current Injection:** None
- **Flakiness Risk:** Low/Medium (Log non-determinism, potential test slowdowns/races)
- **Recommended Provider:** `Clock`

## Network
- **Source:** `requests`
- **Citations:**
  - `utils/lmstudio_tool.py:34`: `requests.post`
  - `agents/batch/sequence.py:13`: `requests.get`
  - `agents/batch/sequence.py:31`: `requests.post`
- **Impacted Entry Points:** `LMStudioTool.ask()`, `is_lm_studio_running()`, `load_model()`
- **Current Injection:** None
- **Flakiness Risk:** **High** (External dependency)
- **Recommended Provider:** `NetworkProvider`

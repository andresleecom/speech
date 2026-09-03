# MAP log: release 2 ergonomics

| # | Task | Strikes | Verdict | Commit |
|---|------|---------|---------|--------|
| 01 | Microphone menu: one entry per physical mic, rebuilt on device changes | 0 | pass, executor-switch (codex-sol: grok API 500 x3), two spec follow-ups (pseudo-devices, refresh placement) | d147e2a |
| 02 | Windows: do not paste when the target window changed | 0 | pass, executor-switch (codex-sol) | fb860d8 |
| 03 | Push-to-talk on Windows keyboard hotkeys | 0 | pass, executor-switch (codex-sol); verified on the real engine with synthetic key presses | 26b144f |
| 04 | Hotkey editor polish and conflict-free defaults | 0 | pass, executor-switch (opus: grok 500 and codex 404 twice; first opus attempt died on a 529) | 14879bf |
| 05 | Hotkey editor chord capture and OEM keys | 0 | pass; spec follow-up r2 (layout-independent OEM mapping); verified in the real Tk dialog and against both installed layouts | f0eabb4 |

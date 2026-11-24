# Decisions

## D1 — Single-process FastAPI app with background threads (Phase 1)
Simplest local deployment; no broker. Stage status lives in SQLite so a restart shows failed/interrupted stages and they can be resumed.

## D2 — Server-rendered Jinja2 UI
No JS build toolchain for a nontechnical user to install. Small inline JS only for status polling.

## D3 — SQLite with JSON stage artifacts
Each stage artifact is a pydantic model stored as JSON in `projects.state`; media lives in project folders. Easy to inspect, back up and migrate.

## D4 — First supported app is a bundled sandbox spreadsheet
Excel desktop is not available and Google Sheets requires real accounts. A bundled, network-isolated HTML spreadsheet with synthetic data gives a reproducible environment to prove the whole pipeline. It is labelled as a test application in the registry and is never presented as a third-party product.

## D5 — Playwright pinned to 1.63.0
Matches the Chromium build available in the dev container (and gives reliable built-in video recording). Upgrade deliberately, together with `playwright install chromium`.

## D6 — Rendered cursor overlay
Headless Chromium does not draw an OS cursor. An injected overlay follows real Playwright mouse events, so the cursor highlight in the recording reflects genuine interactions.

## D7 — Dev voice = FFmpeg libflite, explicitly labelled
Needed to test the pipeline without Azure keys. Only usable in development mode with per-project opt-in; renders are watermarked "DEVELOPMENT VOICE — NOT FOR PUBLICATION" and are blocked by the publishing gate. edge-tts is not used.

## D8 — Planning from adapter workflow definitions until research is implemented
The plan clearly states that no external research or LLM was used. Steps stay "planned" until the demonstration verifies them.

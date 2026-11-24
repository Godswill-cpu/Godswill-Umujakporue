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

## D9 — Manual capture is verified by human attestation, and labelled as such
For software without an adapter (e.g. Excel desktop) the user uploads their own recording, marks step times
and attests that it shows each step succeeding. The verification record carries `method: human_attested`;
QC adds a human-judgement warning and the YouTube description says "Recorded by the creator" instead of
"Tested". Unknown environment fields stay unknown. Screenshots are frames of the uploaded recording only.
Attestation is cleared whenever the recording, steps or environment details change.

## D10 — Research findings must quote their fetched source verbatim
The LLM only sees pages the app actually fetched. Each finding must include an exact quote; the app checks it
(after whitespace/case/punctuation-icon normalisation) against the extracted page text and discards any finding
that fails, listing it as a rejected claim. Findings are labelled "sourced, not demonstrated" and never change the
tested steps. Discrepancies (e.g. different menu names) become plan warnings and QC items for human review.

## D11 — Claude as the first LLM provider, behind `LLMProvider`
`studio/llm/base.py` defines `structured(system, user, schema)`. The Anthropic implementation uses structured
outputs (`beta.messages.parse`, pydantic schema), effort `high`, and server-side refusal fallbacks. Research
results are cached by a hash of the prompt and sources; usage is recorded per project against a token budget.

## D12 — Azure transports: SDK first, REST API when the SDK cannot connect
Both are official Azure Speech integrations using the same neural voices. The SDK (WebSocket) also returns
word-boundary timings; the REST API does not. `AZURE_SPEECH_TRANSPORT=auto` (default) tries the SDK and, only on a
connection failure, switches to REST and logs it. Authentication or request errors never trigger a switch, and
nothing ever falls back to a non-Azure voice. `sdk` or `rest` can be forced.

## D13 — Scene transitions
Only the first scene fades in after the title card. Footage between steps is continuous, so per-scene fades produced
distracting dips to black and were removed.

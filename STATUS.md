# Status — 2026-11-24

**Current phase:** Phases 1–3 complete for the supported workflow; the §14 acceptance test has **passed live** (see below). Phase 4 partly done.
Azure Neural TTS run (no credentials available in the development environment).

Test suite: `pytest -q` → **41 passed** (incl. 1 live Azure test when credentials are set) (real Chromium + real FFmpeg; dev voice for narration).

## Live acceptance test (§14) — PASSED 2026-11-24
`scripts/acceptance_run.py` drives the real dashboard in Chromium with the app in **production mode** (no dev voice
possible) and **real Azure Neural TTS (eastus, en-US-AndrewNeural)**: project created via the Create form →
plan → real Playwright demonstration → automated verification passed → script → Azure narration → 1920×1080 MP4
(69 s, −16.2 LUFS) with captions and chapters → QC (0 blockers) → narration approval → final approval → export
ZIP with MP4, SRT, audio, YouTube metadata, thumbnail, QC report and version-verification record. 13/13 steps passed.

Caveats, stated plainly:
- The approval clicks in that run were made by the script, proving the approval workflow — not a human review of the video.
- The application is the bundled Studio Sandbox Sheet, not Excel (unavailable in the dev container).
- In the dev container the Azure Speech **SDK** WebSocket is blocked by the network proxy, so narration used the
  official Azure Speech **REST** API (same neural voices, no word-boundary timings → captions timed by text length).
  The SDK path is implemented but has not completed a live synthesis.

## Implemented and tested
| Area | Evidence |
|---|---|
| Config: env/.env/secrets.env, secret redaction, 600 perms, settings page never echoes key | `test_foundation`, `test_web` |
| SQLite storage: projects, stages, events, TTS usage | `test_foundation` |
| Data contracts between all modules | used by all tests |
| Registry of supported / planned / unsupported apps; unsupported apps cannot be automated | `test_foundation`, `test_web` |
| Dashboard: dashboard, create video (+discovery mode), project page with all sections, registry, settings | `test_web`, e2e test |
| Planning from tested workflow definitions with honest research note and warnings | `test_foundation` |
| Playwright demonstration engine: isolated env, network blocking, real video, screenshots, cursor highlight, step assertions, stop-on-failure | `test_integration` |
| Version detection (app name/edition/version/build, OS, platform, browser) + verification record | e2e test |
| Compatibility check (missing/renamed controls) and wrong-result detection | `test_failed_demonstrations…` |
| Script generation only from verified runs, numbers from observed state, difficulty adaptation | e2e + negative tests |
| Script editing invalidates narration/render/QC and approvals | e2e test |
| Narration policy: production never falls back; dev voice requires explicit opt-in | `test_narration_policy` |
| SSML (pronunciation `<sub>`, rate, pauses, escaping) | `test_narration_policy` |
| TTS caching + per-project character limit + silent-audio check | exercised in e2e (dev voice) |
| FFmpeg assembly: title card, scene sync (hold last frame until narration ends), contextual zoom, step callouts, fades, burned + SRT captions, loudness normalization, chapters | `test_rendering`, e2e |
| QC: media validity, demo failures, missing steps, missing narration, dev voice, sync, silence, caption timing, resolution, duration, repetition, licensing note, human-judgement items | e2e |
| Publishing gate (verified demo, no QC blockers, production narration approved, version ack) | `test_narration_policy`, e2e negative |
| Manual-capture fallback: upload own recording, mark steps, enter environment, attest; frames extracted from the recording; verification labelled `human_attested`; any change clears attestation; 4:3 etc. padded not stretched | `test_manual_capture` |
| Research-assisted planning: fetches real documentation (https only, size limits), extracts text, asks the LLM for findings with verbatim quotes, **keeps only findings whose quote is found in the fetched source**, reports discarded claims, discrepancies with the tested workflow and uncertain statements; cached; per-project token budget | `test_research` (labeled fake LLM + real fetch of an official Google help page) |
| Sourced troubleshooting tips in narration (by difficulty), shown over the verified final state, flagged for human review in QC | `test_research` |
| Azure Neural TTS (live, eastus): SSML, voices, rate, pronunciations, REST transport, auth/400 errors, auto-switch from SDK when it cannot connect | `test_publishing_azure` (live), acceptance run |
| Resumable stages ("Run from here"), background jobs, activity log | e2e |

## Implemented, NOT tested live
- **Azure Speech SDK transport** (WebSocket, word-boundary timings): blocked by the dev container's proxy; REST transport is tested live.
- **Anthropic (Claude) provider** for research (`studio/llm/anthropic_provider.py`: official SDK, structured outputs via `beta.messages.parse`, server-side refusal fallbacks, typed error handling). No API key in the dev environment, so it has never run live. **Blocked on credentials.**
- Voice preview endpoint with Azure (works with dev voice).
- Reverification list on the registry page (simple rules: >90 days, unknown version, version no longer tested).

## Partially implemented
- Research uses only URLs the user lists (plus registry doc URLs, none configured yet); there is no automatic source discovery/web search.
- Research does not change the tested step sequence; it annotates it (notes, prerequisites, discrepancies, tips).
- Script adaptation: difficulty level + sourced tips; no LLM rewriting of narration.
- Captions timed by character share when word timings are absent (dev voice); Azure word timings used when present.

## Planned (not started)
- Automatic documentation discovery (web search) and LLM-assisted script polishing.
- Additional adapters (Google Sheets with test account first); desktop automation adapters.
- Optional authorized YouTube upload.
- Automation-time measurement (needed before any claim about the 85% target).

## Known limitations
- The only supported application is the bundled **Studio Sandbox Sheet** test app, not a third-party product.
  Excel desktop is unavailable in the dev container; the acceptance test cannot use it.
- YouTube chapters are merged to satisfy YouTube's rules (≥3 chapters, each ≥10 s); the review page keeps every scene.
- No claim about the 85% automation target can be made yet.

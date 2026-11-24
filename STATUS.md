# Status — 2026-11-24

**Current phase:** Phase 1 complete. Phases 2–3 vertical slice implemented and tested *except* a live
Azure Neural TTS run (no credentials available in the development environment).

Test suite: `pytest -q` → **27 passed** (real Chromium + real FFmpeg; dev voice for narration).

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
| Resumable stages ("Run from here"), background jobs, activity log | e2e |

## Implemented, NOT tested live
- **Azure Neural TTS provider** (`studio/tts/azure.py`, official Speech SDK, SSML, word-boundary timings,
  retries, auth errors). Only provider selection is tested. Needs a real key to validate. **Blocked on credentials.**
- Voice preview endpoint with Azure (works with dev voice).
- Export package + thumbnail: code path only reachable after Azure narration is approved, so not yet exercised end to end.
- Reverification list on the registry page (simple rules: >90 days, unknown version, version no longer tested).

## Partially implemented
- Research: plans come from the adapter's workflow definition; no web research or LLM planning.
- Script adaptation: difficulty only; no LLM rewriting, no troubleshooting section generation.
- Captions timed by character share when word timings are absent (dev voice); Azure word timings used when present.

## Planned (not started)
- Manual capture / human-verified fallback for unsupported workflows.
- Provider-agnostic LLM integration (research-assisted planning, adaptive scripts).
- Additional adapters (Google Sheets with test account first); desktop automation adapters.
- Optional authorized YouTube upload.
- Automation-time measurement (needed before any claim about the 85% target).

## Known limitations
- The only supported application is the bundled **Studio Sandbox Sheet** test app, not a third-party product.
  Excel desktop is unavailable in the dev container; the acceptance test cannot use it.
- The §14 acceptance test is **not yet passed**: step 7 (Azure narration) and the approval/export steps that
  depend on it have not been run live.
- No claim about the 85% automation target can be made yet.

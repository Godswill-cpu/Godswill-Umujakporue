# Roadmap

Development follows a vertical-slice-first strategy: one browser workflow is proven end to end before
any other application is added.

## Phase 1 — Foundation and reliability (effort: MEDIUM)
Project structure, data contracts, configuration + secret handling, SQLite schema, dashboard foundations
(dashboard, create project, project page, registry, settings), logging/error handling, FFmpeg rendering
foundations, version-metadata contract, tests, reproducible install docs.
**Done when:** the app starts reliably, projects can be created and stored, foundational tests pass.

## Phase 2 — Verified demonstration engine (effort: HIGH)
Playwright engine, application adapter interface, first adapter (bundled Studio Sandbox Sheet,
"remove duplicate rows"), real recording + screenshots, cursor highlight, version detection,
compatibility checks, end-state verification, failure handling, manual-capture fallback (upload).
**Done when:** one supported tutorial is executed, recorded and verified through the application.

## Phase 3 — AI production engine (effort: HIGH)
Research-assisted planning (provider-agnostic LLM with structured outputs, real sources only),
adaptive scripts from observed results, Azure Neural TTS (SSML, voices, previews, rate,
pronunciations, word timings), narration/footage sync, FFmpeg assembly (zooms, callouts, branding,
loudness normalization), captions, production QC.
**Done when:** a verified demonstration becomes a narrated tutorial video ready for human review.

## Phase 4 — Integrated application and publishing (effort: MEDIUM)
Job management, review tools, version/compatibility warnings, approval workflow, export packages,
optional authorized YouTube upload, reverification list, installer polish, end-to-end + negative tests,
maintenance/troubleshooting docs.
**Done when:** a nontechnical user can create, produce, review, approve and export a supported tutorial
entirely through the UI.

## After Phase 4
Additional adapters (Google Sheets with a dedicated test account first), desktop automation adapters,
automation-time measurement to evidence (or refute) the 85% target.

## Progress (2026-11-24)
- Phase 1 ✅ · Phase 2 ✅ (sandbox adapter + manual capture) · Phase 3 ✅ for the supported workflow (live Azure; LLM research untested live)
- Phase 4: job management ✅, crash recovery ✅, approval/export ✅, automation measurement ✅, installers ✅ (Windows untested),
  YouTube upload ⏳ (needs Google OAuth credentials + explicit authorization), Google Sheets adapter ⏳ (needs test account)

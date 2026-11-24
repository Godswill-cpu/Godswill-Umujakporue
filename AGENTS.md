# AGENTS.md — Permanent AI development instructions

These rules bind every AI agent (and human) working on Automated Software Tutorial Studio.
The full specification is the Master Development Prompt summarised in `PROJECT_SCOPE.md`.

## Product
- A locally hosted, browser-accessible app that turns a software-tutorial topic into a verified,
  narrated, edited YouTube tutorial with ~85% automation of repetitive labour.
- Scope is **software tutorials only**. Never expand into cinematic/AI video generation, storytelling,
  documentaries, social-media management or unrelated creator tools.

## Non-negotiable rules
1. Do not change the product vision or add major features without explicit approval.
2. Vertical slice first: prove one workflow end to end before widening support.
3. Never fabricate demonstrations, screenshots, sources, or software version information.
   Unknown values are stored as unknown (`null`), never guessed.
4. Never claim an integration is tested unless a test or live run actually exercised it.
   Mocks are allowed only in explicitly labeled development tests.
5. Azure AI Speech Neural TTS is the production narration provider. The robotic dev voice may be used
   only in development mode with explicit per-project opt-in; its output is watermarked and can never
   pass the publishing gate. Never fall back silently.
6. No publication without explicit human approval. Failed or unverified demonstrations can never be
   approved or exported as finished tutorials.
7. Never commit credentials. Secrets live in env vars or `data/secrets.env` (gitignored, mode 600) and
   are redacted from logs, errors and exports.
8. Use isolated test environments and synthetic data. Block network access outside the test
   environment during demonstrations. Stop on unexpected behaviour; never improvise actions.
9. No destructive operations, external account changes, purchases or publishing without authorization.
10. Keep modules independently testable and communicating through `studio/contracts.py` models.
11. Avoid unnecessary infrastructure (no microservices, queues, Kubernetes, cloud DBs).
12. Keep `STATUS.md` accurate: Implemented / Tested / Partially implemented / Blocked / Planned.
    Code written is not code complete.

## Working conventions
- Python 3.11+, FastAPI, Jinja2 server-rendered UI, SQLite, Playwright (Chromium), FFmpeg.
- Run `pytest` before every commit. Add tests with every feature.
- Record significant choices in `DECISIONS.md`; update `STATUS.md` at every milestone.
- At each milestone report: implemented, tested, failed, incomplete, current phase,
  recommended thinking effort for the next task.

# Architecture

Simplest architecture that can reach the full product: **one local Python process** (FastAPI) that
serves a server-rendered dashboard, stores state in SQLite plus per-project folders, and runs pipeline
stages in background threads. No queues, microservices or cloud services except Azure AI Speech.

```
 Browser (dashboard, Jinja2 + minimal JS)
          │ HTTP (127.0.0.1)
 ┌────────▼─────────────────────────────────────────────────────────────┐
 │ studio.web.app (FastAPI)                                              │
 │   pages + JSON API ──► studio.pipeline (stage runner, background jobs) │
 │                            │                                          │
 │   planning ─► demo_engine ─► scripting ─► narration ─► video ─► qc ─► publishing
 │      │            │              │            │           │        │        │
 │   registry   adapters/*      contracts     tts/*        media     contracts  export zip
 │                (Playwright)               (Azure SDK | dev flite) (FFmpeg)          │
 │                                                                                      │
 │ studio.db (SQLite: projects, stages, events, usage)   data/projects/<id>/…  files    │
 │ studio.config (env + data/secrets.env, SecretStr, redaction)                          │
 └──────────────────────────────────────────────────────────────────────────────────────┘
```

## Modules and boundaries
| Module | Responsibility | Inputs → Outputs (contracts.py) |
|---|---|---|
| `config` | env/.env/secrets.env loading, secret redaction, preferences | → `Settings` |
| `db` | SQLite persistence, stage status, event log, TTS usage | project rows, stage rows |
| `registry` | explicit list of apps/platforms/versions/workflows and their support status | → `AppEntry`, adapter |
| `planning` | topic discovery, tutorial plan | `ProjectRequest` → `TutorialPlan` |
| `research/*` + `llm/*` | fetch docs, quote-verified LLM findings, provider abstraction | `ProjectRequest`, URLs → `ResearchReport` (in `TutorialPlan.research`) |
| `adapters/*` | app-specific: environment, version detection, end-state verification | `WorkflowSpec`, `EnvironmentRecord`, `Check` |
| `demo_engine` | generic Playwright runner: isolation, recording, screenshots, step assertions | → `ExecutionResult` + `VerificationRecord` |
| `manual_capture` | fallback: user recording + step marks + attestation → `ExecutionResult` (method `human_attested`) | upload → `ExecutionResult` |
| `scripting` | narration text from observed results of successful steps | `ExecutionResult` → `TutorialScript` |
| `tts/*` + `narration` | provider abstraction, Azure SDK, dev voice, caching, limits, audio QC | `TutorialScript` → `NarrationResult` |
| `media` + `video` | FFmpeg probing and assembly, captions, chapters | → `RenderResult` |
| `qc` | automated checks + human-judgement items | → `QCReport` |
| `publishing` | approval gate, metadata, thumbnail brief, export package | → `PublishingPackage` |
| `pipeline` | runs stages in order, resumable, invalidates downstream stages on edits | |
| `web` | dashboard pages and API | |

## Key interfaces
- `AppAdapter` (`studio/adapters/base.py`): `workflows()`, `environment_url()`, `allowed_url_prefixes()`,
  `wait_ready()`, `detect_environment()`, `observe_before()`, `verify()`.
- `TTSProvider` (`studio/tts/base.py`): `name`, `production_grade`, `voices()`, `synthesize()`.
  Swapping narration services = adding a provider class; nothing else changes.

## Storage layout
```
data/
  studio.sqlite3
  secrets.env            (mode 600, gitignored)
  preferences.json
  cache/tts/<hash>.wav   (narration cache, avoids re-billing)
  projects/<id>/runs/<run_id>/{recording.webm, screenshots/, execution.log, verification.json}
  projects/<id>/narration/  render/  export/
```

## Safety boundaries
- Demonstrations run in a fresh browser context; requests outside the adapter's allowed URL prefixes are blocked.
- First unexpected behaviour aborts the run; failure screenshot + log are kept as evidence.
- Publishing gate (`publishing.check_gate`) requires: verification passed, no unresolved QC blockers,
  production-grade narration approved by the user, version limitation acknowledged if unknown, and
  explicit final approval.

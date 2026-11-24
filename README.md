# Automated Software Tutorial Studio

A locally hosted web application that turns a software-tutorial topic into a **verified, narrated, edited
tutorial video**: it executes the workflow for real in an isolated environment, records it, verifies the
result, writes narration from what actually happened, narrates it with Azure Neural TTS, assembles a 16:9 MP4
with captions, runs quality control and — only after your approval — exports the video and YouTube metadata.

> **Current state:** two supported applications run end to end with live Azure narration: a bundled test
> spreadsheet ("remove duplicate rows") and **JupyterLab 4** ("create and run your first notebook"). Other software
> can be used through manual capture. See [STATUS.md](STATUS.md) for exactly what is
> implemented, tested and still missing.

## Requirements
- Python 3.11+
- FFmpeg with `libass` (captions) — `ffmpeg -filters | grep subtitles` should list it.
  `libflite` is optional (only for the development voice).
- Chromium for Playwright (installed below)
- Azure AI Speech resource (key + region) for production narration

## Install
**Easiest:** macOS/Linux `./install.sh` then `./start.sh`; Windows: right-click `install.ps1` → *Run with PowerShell*,
then double-click `start.bat`. The browser opens at http://127.0.0.1:8765.

Manual install:
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env                                   # optional; every value has a default
```

## Run
```bash
python -m studio
```
Open http://127.0.0.1:8765. Everything else happens in the browser:

1. **Settings** → paste your Azure Speech key and region (stored in `data/secrets.env`, mode 600, never shown again).
2. **Create video** → pick the workflow, voice, difficulty, resolution → *Create project* (production starts automatically).
3. Watch the pipeline on the project page: plan → verified demonstration → script → narration → video → QC.
4. Review the raw recording, screenshots and verification checks; edit the script; preview voices and add pronunciation fixes.
5. Listen to the narration and approve it; watch the final video.
6. Grant final approval → *Build export package* → download the ZIP (MP4, SRT, audio, YouTube metadata, thumbnail,
   QC report, version-verification record).

### Research-assisted planning (optional)
In **Settings**, choose *Anthropic (Claude)* as the AI provider and paste an API key. When creating a project,
list documentation URLs (official help pages preferred). The app fetches them, asks the model for findings that
each quote the page verbatim, and discards any finding whose quote is not actually on the page. Findings appear in
*Research & planning*; troubleshooting findings can be added to the narration as clearly flagged tips.

### Software without an automation adapter (manual capture)
Choose **Manual capture** on *Create video*, then on the project page upload your own screen recording, list
when each step starts (`0:12 | Step title | narration`), fill in the version details you know and confirm the
recording shows every step succeeding. The rest of the pipeline (narration, assembly, QC, approval, export)
is identical; the video is labelled as human-verified rather than automatically verified.

### Without Azure (development only)
In development mode a project can explicitly opt in to a **robotic offline voice** (FFmpeg libflite) to test
the pipeline. Such videos are watermarked "DEVELOPMENT VOICE – NOT FOR PUBLICATION" and can never be approved or
exported. Production mode (`STUDIO_MODE=production`) never uses it.

## Measuring automation
Enter on *Create video* (or later on the project page) how many minutes the tutorial would take you by hand.
The app counts your active time and interventions per project and, after final approval, reports the share of
your baseline saved on the dashboard. Nothing is estimated without your baseline.

## Configuration
Environment variables (or `.env`) override Settings-page values:

| Variable | Default | Meaning |
|---|---|---|
| `STUDIO_MODE` | `development` | `production` forbids non-Azure narration |
| `STUDIO_DATA_DIR` | `./data` | database, projects, cache, secrets |
| `STUDIO_HOST` / `STUDIO_PORT` | `127.0.0.1` / `8765` | bind address |
| `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` | — | Azure AI Speech credentials (region id, e.g. `eastus`) |
| `AZURE_SPEECH_TRANSPORT` | `auto` | `sdk`, `rest`, or `auto` (SDK, REST if the SDK cannot connect) |
| `STUDIO_MAX_TTS_CHARS_PER_PROJECT` | `20000` | cost limit (cached segments are not counted) |
| `STUDIO_CHROMIUM_EXECUTABLE` | — | explicit Chromium path |
| `STUDIO_LLM_PROVIDER` | `none` | `anthropic` enables AI research |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (or set it in Settings) |
| `STUDIO_LLM_MODEL` | `claude-opus-5-5` | model used for research |
| `STUDIO_MAX_LLM_TOKENS_PER_PROJECT` | `300000` | AI research budget per project |

## Live acceptance run
With real Azure credentials, run the full dashboard-driven acceptance test (production mode, nothing mocked):
```bash
AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=eastus python scripts/acceptance_run.py --out acceptance-output
```
It writes screenshots, the export ZIP and `acceptance_report.json` (13 checked steps).

## Tests
```bash
pytest -q
```
Integration tests drive real Chromium and FFmpeg (≈2 minutes). Narration in tests uses the labeled development
voice because CI has no Azure key; those tests assert that such output is **blocked** from publishing.

## Troubleshooting
- *"Executable doesn't exist … chromium"*: run `python -m playwright install chromium`, or set `STUDIO_CHROMIUM_EXECUTABLE`.
- *Narration stage fails with "Azure AI Speech is not configured"*: add key + region in Settings, then *Run from here* on Narration.
- *"authentication failed"*: wrong key/region pair.
- *Log says the Speech SDK could not connect*: a proxy/firewall blocks WebSockets; narration continues over the Azure REST API (captions then lack word-level timing). Set `AZURE_SPEECH_TRANSPORT=rest` to skip the SDK attempt.
- *Render fails mentioning `subtitles`*: your FFmpeg lacks libass; install a full FFmpeg build.
- Any failed stage can be retried with **Run from here**; earlier completed stages are not repeated.
- Logs: `data/studio.log` and each project's activity log; per-run `execution.log` and `verification.json`.

## Documentation
[PROJECT_SCOPE](PROJECT_SCOPE.md) · [ARCHITECTURE](ARCHITECTURE.md) · [ROADMAP](ROADMAP.md) ·
[STATUS](STATUS.md) · [DECISIONS](DECISIONS.md) · [AGENTS](AGENTS.md)

# Project scope — Automated Software Tutorial Studio

## Vision
A nontechnical user opens a local web dashboard, enters a software-tutorial topic, selects target
software/platform/preferences, and the app: plans the tutorial from reliable sources, executes and
records a **real** demonstration, verifies the result, writes a script describing what actually
happened, narrates it with Azure Neural TTS, assembles an edited 16:9 MP4 with captions, runs quality
control, and — after mandatory human approval — exports the video and YouTube metadata.

Target: ~85% reduction in human labour time for supported workflows. This is a goal measured by
evidence, not a guarantee.

## In scope
- Tutorials demonstrating real software workflows (spreadsheets, productivity apps, supported web apps,
  other software reliably operable through tested adapters).
- Dashboard sections: Dashboard, Create Video, Research & Planning, Demonstration Manager, Script
  Editor, Voice Studio, Video Review, Quality Control, Publishing, Settings.
- Pipeline: topic discovery (manual + discovery mode) → research/planning → verified demonstration →
  adaptive script → Azure narration → FFmpeg assembly → QC + human approval → export/publishing.
- Mandatory software version verification and verification records.
- Cost control: usage limits, caching, retries, resumable stages.

## Out of scope (non-negotiable)
AI cinematic filmmaking, documentaries, fiction, general image-to-video, social media management,
multi-channel networks, unrelated creator tools, evasion of platform detection.

## Human responsibilities (never automated away)
Creative decisions, verification of high-impact claims, ambiguous steps, correcting technical errors,
approving narration, reviewing the finished video, authorizing publication.

## Acceptance test (§14)
Dashboard-driven end-to-end run: create project → select environment → plan → real actions → recording →
verification → Azure narration → sync → render → captions + metadata → verification/QC reports →
human approval → export. Plus negative tests proving failed/unverified tutorials cannot be published.
Excel desktop is not available in the development container; the first end-to-end validation uses a
bundled browser-based test application, and that limitation is documented.

"""Stage 7: automated quality control plus explicit human-judgement items."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .contracts import (ExecutionResult, NarrationResult, ProjectRequest, QCItem, QCReport, RenderResult,
                        TutorialPlan, TutorialScript)
from .media import MediaError, probe, silences


def run_qc(project_dir: Path, req: ProjectRequest, plan: TutorialPlan | None, execution: ExecutionResult | None,
           script: TutorialScript | None, narration: NarrationResult | None, render: RenderResult | None) -> QCReport:
    items: list[QCItem] = []
    def add(id: str, severity: str, category: str, message: str, automated: bool = True) -> None:
        items.append(QCItem(id=id, severity=severity, category=category, message=message, automated=automated))

    # --- demonstration & verification ---------------------------------
    if not execution:
        add("demo-missing", "blocker", "demonstration", "No demonstration has been run.")
    else:
        v = execution.verification
        if v.outcome != "passed":
            failed = [c.name for c in v.checks if not c.passed]
            add("demo-failed", "blocker", "demonstration", f"Demonstration not verified ({v.outcome}): {', '.join(failed) or 'see log'}.")
        for w in v.compatibility_warnings:
            sev = "warning" if "version" in w.lower() else "blocker"
            add(f"compat-{abs(hash(w)) % 10**6}", sev, "compatibility", w)
        if v.method == "human_attested":
            add("verification-human", "warning", "verification", "Manual capture: the result was verified by your "
                "attestation, not by automated inspection of the application. Re-watch every step carefully.",
                automated=False)
        env = v.environment
        if not env.app_version:
            add("version-unknown", "warning", "version", "Software version unknown. The tested environment is documented; "
                "you must acknowledge this limitation before approval.")
        if req.target_version and env.app_version and req.target_version not in env.app_version:
            add("version-mismatch", "warning", "version",
                f"Requested version {req.target_version} but demonstrated on {env.app_version}.")
        if plan:
            ran = {s.step_id for s in execution.steps if s.status == "ok"}
            missing = [s.title for s in plan.steps if s.step_id not in ran]
            if missing:
                add("steps-missing", "blocker", "steps", "Planned steps not demonstrated: " + "; ".join(missing))
        if execution.video_path and not (project_dir / execution.video_path).exists():
            add("recording-missing", "blocker", "media", "Demonstration recording file is missing.")
        for s in execution.steps:
            if s.screenshot and not (project_dir / s.screenshot).exists():
                add(f"shot-missing-{s.step_id}", "warning", "media", f"Screenshot missing for step '{s.title}'.")

    if plan and plan.generated_by == "workflow-registry":
        add("research-not-automated", "info", "research",
            "Plan came from the tested workflow definition; no external research was performed.")

    # --- script --------------------------------------------------------
    if not script:
        add("script-missing", "blocker", "script", "No script.")
    else:
        sentences = [s.strip().lower() for seg in script.segments for s in re.split(r"(?<=[.!?])\s+", seg.text) if len(s.strip()) > 15]
        dup = [s for s, n in Counter(sentences).items() if n > 1]
        if dup:
            add("script-repetitive", "warning", "script", f"Repeated sentences: {dup[:3]}")
        if execution:
            ok = {s.step_id for s in execution.steps if s.status == "ok"}
            unsupported = [seg.id for seg in script.segments if seg.kind == "step" and seg.step_id not in ok]
            if unsupported:
                add("script-unsupported-steps", "blocker", "claims", f"Script describes steps not demonstrated: {unsupported}")
        if script.edited:
            add("script-edited", "warning", "claims", "Script was edited by hand. Confirm every statement matches the "
                "recording (automated claim checks only cover generated text).", automated=False)

    # --- narration -----------------------------------------------------
    if not narration:
        add("narration-missing", "blocker", "audio", "No narration.")
    else:
        if script:
            got = {s.segment_id for s in narration.segments}
            miss = [s.id for s in script.segments if s.id not in got]
            if miss:
                add("narration-segments-missing", "blocker", "audio", f"Missing narration for: {miss}")
        for s in narration.segments:
            if not Path(s.audio_path).exists():
                add(f"narration-file-{s.segment_id}", "blocker", "media", f"Narration audio missing: {s.segment_id}")
        if not narration.production_grade:
            add("narration-dev-voice", "blocker", "audio", f"Narration uses '{narration.provider}', a development-only voice. "
                "Re-narrate with Azure Neural TTS before publication.")

    # --- render --------------------------------------------------------
    if not render:
        add("render-missing", "blocker", "render", "No rendered video.")
    else:
        vp = Path(render.video_path)
        try:
            info = probe(vp)
            streams = {s["codec_type"] for s in info["streams"]}
            if streams != {"video", "audio"}:
                add("render-streams", "blocker", "render", f"Rendered file streams: {sorted(streams)}")
            vs = next(s for s in info["streams"] if s["codec_type"] == "video")
            if f"{vs['width']}x{vs['height']}" != req.resolution:
                add("render-resolution", "blocker", "render", f"Resolution {vs['width']}x{vs['height']} != {req.resolution}")
            if abs(render.duration - req.target_duration_s) > max(20, req.target_duration_s * 0.5):
                add("duration-target", "warning", "render", f"Duration {render.duration:.0f}s vs target {req.target_duration_s}s. "
                    "Content is not padded to reach a target.")
            # unexpected silence after the title card
            for a, b in silences(vp, min_len=3.0):
                if b > 3.5:
                    add(f"silence-{int(a)}", "warning", "audio", f"Silent section {a:.1f}s-{b:.1f}s.")
        except (MediaError, StopIteration) as e:
            add("render-invalid", "blocker", "render", f"Rendered video is invalid: {e}")
        if not Path(render.srt_path).exists():
            add("captions-missing", "blocker", "captions", "Caption file missing.")
        prev = 0.0
        for c in render.cues:
            if c.start < prev - 1e-3 or c.end <= c.start or c.end > render.duration + 0.5:
                add("captions-timing", "blocker", "captions", f"Caption timing problem at {c.start:.2f}s: '{c.text[:40]}'")
                break
            prev = c.end
        if narration and render.duration + 0.5 < narration.total_duration:
            add("sync-short", "blocker", "sync", "Video is shorter than its narration.")

    if execution and execution.verification.method == "human_attested":
        add("media-licensing", "warning", "licensing", "Footage was uploaded by you. Confirm you own the rights to it "
            "and that it shows no private or sensitive data.", automated=False)
    else:
        add("media-licensing", "info", "licensing", "All footage is the app's own recording, title cards are generated, "
            "and no third-party music or images are used.")
    # --- human judgement (never automated) -----------------------------
    add("human-narration", "info", "human review", "Listen to the full narration and approve it in Voice Studio.", automated=False)
    add("human-video", "info", "human review", "Watch the full video; confirm narration matches what is on screen.", automated=False)
    add("human-claims", "info", "human review", "Confirm any high-impact or general claims are accurate.", automated=False)
    return QCReport(items=items)

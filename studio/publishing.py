"""Stage 8: approval gate, YouTube metadata, thumbnail and export package.

No upload happens here. YouTube integration is a later, separately authorized phase.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from .contracts import (Approval, ExecutionResult, NarrationResult, PublishingPackage, QCReport, RenderResult,
                        TutorialPlan, TutorialScript)
from .media import run_ffmpeg


def check_gate(execution: ExecutionResult | None, narration: NarrationResult | None, render: RenderResult | None,
               qc: QCReport | None, approval: Approval) -> list[str]:
    """Reasons the project cannot be approved/exported. Empty list = gate open."""
    reasons = []
    if not execution or execution.verification.outcome != "passed":
        reasons.append("The demonstrated task was not successfully verified.")
    if not render:
        reasons.append("No rendered video.")
    if not qc:
        reasons.append("Quality control has not run on the current render.")
    else:
        reasons += [f"QC blocker: {b.message}" for b in qc.blockers]
    if not narration or not narration.production_grade:
        reasons.append("Narration is not production grade (Azure Neural TTS required).")
    if narration and not approval.narration_approved_at:
        reasons.append("Narration has not been listened to and approved.")
    if execution and not execution.verification.environment.app_version and not approval.version_limitation_acknowledged:
        reasons.append("Software version is unknown and the limitation has not been acknowledged.")
    return reasons


def _ts(t: float) -> str:
    t = int(t)
    return f"{t//60}:{t%60:02d}" if t < 3600 else f"{t//3600}:{t//60%60:02d}:{t%60:02d}"


YT_MIN_CHAPTER_S = 10


def youtube_chapters(chapters, duration: float) -> list[tuple[float, str]]:
    """YouTube ignores chapters unless the first starts at 0:00, there are at least three, and each lasts
    at least 10 seconds. Merge short chapters into their neighbour; return [] if rules still fail."""
    items = [[c.start, c.title] for c in chapters]
    if not items:
        return []
    items[0][0] = 0.0
    i = 0
    while i < len(items):
        end = items[i + 1][0] if i + 1 < len(items) else duration
        if end - items[i][0] < YT_MIN_CHAPTER_S and len(items) > 1:
            if i + 1 < len(items):  # merge the next chapter into this one
                items[i][1] = f"{items[i][1]} & {items[i + 1][1]}"
                del items[i + 1]
            else:  # last chapter too short: merge into previous
                items[i - 1][1] = f"{items[i - 1][1]} & {items[i][1]}"
                del items[i]
            continue
        i += 1
    for t in items:
        t[1] = t[1].replace("& Result", "and result")[:100]
    return [(a, b) for a, b in items] if len(items) >= 3 else []


def build_metadata(plan: TutorialPlan, execution: ExecutionResult, render: RenderResult, script: TutorialScript) -> PublishingPackage:
    env = execution.verification.environment
    yt = youtube_chapters(render.chapters, render.duration)
    chapters = "\n".join(f"{_ts(t)} {title}" for t, title in yt)
    steps = "\n".join(f"{i}. {s.title}" for i, s in enumerate([s for s in execution.steps if s.status == "ok"], 1))
    desc = (f"{plan.summary}\n\nSteps shown:\n{steps}\n\n" + (f"Chapters:\n{chapters}\n\n" if chapters else "") +
            f"{'Recorded by the creator' if execution.verification.method == 'human_attested' else 'Tested'} on {env.app_name} {env.app_version or '(version unknown)'}"
            f"{' build ' + env.app_build if env.app_build else ''}, {env.platform}, "
            f"{env.browser_name or ''} {env.browser_version or ''}, on {env.tested_at[:10]}.\n"
            "Narration voice is AI-generated (Azure Neural TTS).")
    obs = execution.observations
    result = (f"the before/after of the sheet (from {obs['initial_rows']} to {obs['final_rows']} rows)"
              if "initial_rows" in obs and "final_rows" in obs else "the final result exactly as it appears in the video")
    brief = (f"Thumbnail brief: show {result}. Large text: '{plan.title.replace('How to ', '').upper()}'. "
             "Use the real final-state screenshot; do not depict features not shown in the video.")
    return PublishingPackage(title=plan.title[:100], description=desc, chapters_text=chapters,
                             tags=["tutorial", "how to", env.app_name], thumbnail_brief=brief)


def make_thumbnail(screenshot: Path, title: str, out: Path) -> Path:
    from .video import _drawtext
    text = title.replace("How to ", "").upper()[:40]
    run_ffmpeg(["-i", str(screenshot), "-vf", "scale=1280:720,drawbox=x=0:y=470:w=1280:h=250:color=0x0f172a@0.85:t=fill,"
                + _drawtext(text, 64, "540", bold=True), "-frames:v", "1", str(out)])
    return out


def export_package(project_dir: Path, pkg: PublishingPackage, render: RenderResult, execution: ExecutionResult,
                   qc: QCReport, narration: NarrationResult, approval: Approval) -> Path:
    out = project_dir / "export"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(render.video_path, out / "tutorial.mp4")
    shutil.copy(render.srt_path, out / "captions.srt")
    shutil.copy(render.audio_path, out / "narration.m4a")
    if pkg.thumbnail_path:
        shutil.copy(project_dir / pkg.thumbnail_path, out / "thumbnail.png")
    (out / "youtube_metadata.json").write_text(json.dumps({"title": pkg.title, "description": pkg.description,
        "chapters": pkg.chapters_text, "tags": pkg.tags, "thumbnail_brief": pkg.thumbnail_brief}, indent=2))
    (out / "qc_report.json").write_text(qc.model_dump_json(indent=2))
    (out / "version_verification.json").write_text(execution.verification.model_dump_json(indent=2))
    (out / "approval.json").write_text(json.dumps({**approval.model_dump(), "narration_provider": narration.provider}, indent=2))
    zpath = project_dir / "export.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            z.write(f, f.name)
    return zpath

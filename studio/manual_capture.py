"""Manual-capture fallback for software that cannot (yet) be automated reliably.

The user supplies a real screen recording, marks step start times and confirms
the recording shows the task succeeding. Nothing is executed or fabricated:
screenshots are frames extracted from the user's own recording, unknown
environment values stay unknown, and the verification record is labelled
``human_attested`` so it is never mistaken for automated verification.
"""
from __future__ import annotations

import platform
from pathlib import Path

from .contracts import (Check, EnvironmentRecord, ExecutionResult, ManualStep, ProjectRequest, Source, StepResult,
                        StepSpec, VerificationRecord, WorkflowSpec, now_iso)
from .media import MediaError, probe, probe_duration, run_ffmpeg

ALLOWED_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
MAX_UPLOAD_BYTES = 4 * 1024**3


class ManualCaptureError(ValueError):
    pass


def _brace_safe(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def parse_steps(text: str) -> list[ManualStep]:
    """Parse lines of ``mm:ss | title | narration (optional) | expected (optional)``."""
    steps: list[ManualStep] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[1]:
            raise ManualCaptureError(f"Line {n}: expected 'mm:ss | step title | narration'.")
        try:
            t = 0.0
            for piece in parts[0].split(":"):
                t = t * 60 + float(piece)
        except ValueError:
            raise ManualCaptureError(f"Line {n}: '{parts[0]}' is not a time like 0:12 or 1:05.5.") from None
        steps.append(ManualStep(start=t, title=parts[1], narration=parts[2] if len(parts) > 2 else "",
                                expected=parts[3] if len(parts) > 3 else ""))
    if not steps:
        raise ManualCaptureError("Add at least one step.")
    if any(b.start <= a.start for a, b in zip(steps, steps[1:])):
        raise ManualCaptureError("Step times must be in increasing order.")
    return steps


def steps_to_text(steps: list[ManualStep]) -> str:
    def fmt(t: float) -> str:
        return f"{int(t)//60}:{t - int(t)//60*60:04.1f}"
    return "\n".join(" | ".join(x for x in (fmt(s.start), s.title, s.narration, s.expected)) .rstrip(" |") for s in steps)


def workflow_from_manual(req: ProjectRequest) -> WorkflowSpec:
    name = req.manual_app_name or "the application"
    src = Source(id="user-recording", title=f"User-supplied screen recording of {name}", kind="other",
                 note="Steps and narration were written by the user and attested by the user.")
    return WorkflowSpec(
        id="manual", app_id="manual", title=req.topic, summary=f"Manually recorded workflow in {name}.",
        prerequisites=[f"Access to {name}."], sources=[src],
        verification="Human attestation: the user confirmed the recording shows each step and the successful result.",
        intro=_brace_safe(f"In this tutorial you'll see how to {req.topic.removeprefix('How to ').rstrip('.')} in {name}."),
        outro=_brace_safe("That completes the workflow shown in this video."),
        steps=[StepSpec(id=f"m{i}", title=s.title, action="wait", expected=s.expected or "Shown in the recording.",
                        narration=_brace_safe(s.narration or f"Next: {s.title}."), source_ids=["user-recording"],
                        pause_after_ms=0)
               for i, s in enumerate(req.manual_steps, 1)],
    )


def save_upload(fileobj, filename: str, project_dir: Path) -> Path:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ManualCaptureError(f"Unsupported file type '{suffix}'. Use one of {sorted(ALLOWED_SUFFIXES)}.")
    dest_dir = project_dir / "manual"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"recording{suffix}"
    written = 0
    with open(dest, "wb") as out:
        while chunk := fileobj.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise ManualCaptureError("Recording is larger than 4 GB.")
            out.write(chunk)
    try:
        info = probe(dest)
    except MediaError as e:
        dest.unlink(missing_ok=True)
        raise ManualCaptureError(f"The file is not a readable video: {e}") from None
    if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
        dest.unlink(missing_ok=True)
        raise ManualCaptureError("The file has no video stream.")
    return dest


def ingest(project_dir: Path, req: ProjectRequest, capture: dict, log=print) -> ExecutionResult:
    """Turn an uploaded, user-attested recording into an ExecutionResult."""
    if not capture.get("video_path") or not (project_dir / capture["video_path"]).exists():
        raise ManualCaptureError("Waiting for manual capture: upload a screen recording in the Demonstration manager.")
    if not req.manual_steps:
        raise ManualCaptureError("Waiting for manual capture: mark the step times for your recording.")
    if not capture.get("attested_at"):
        raise ManualCaptureError("Waiting for manual capture: confirm that the recording shows every step succeeding.")
    video = project_dir / capture["video_path"]
    info = probe(video)
    vs = next(s for s in info["streams"] if s["codec_type"] == "video")
    duration = probe_duration(video)
    if req.manual_steps[-1].start >= duration:
        raise ManualCaptureError(f"Last step starts at {req.manual_steps[-1].start:.1f}s but the recording is only {duration:.1f}s long.")

    run_id = "manual-" + now_iso().replace(":", "").replace("-", "")[:15]
    shots = project_dir / "runs" / run_id / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    rel = lambda p: str(Path(p).relative_to(project_dir))
    steps: list[StepResult] = []
    for i, s in enumerate(req.manual_steps, 1):
        end = req.manual_steps[i].start if i < len(req.manual_steps) else duration
        shot = shots / f"{i:02d}-m{i}.png"
        # a real frame from the user's recording, shortly before the next step begins
        run_ffmpeg(["-ss", f"{max(s.start, end - 0.5):.2f}", "-i", str(video), "-frames:v", "1", str(shot)])
        steps.append(StepResult(step_id=f"m{i}", title=s.title, status="ok", t_start=s.start, t_end=end,
                                screenshot=rel(shot), message="Marked by the user; outcome attested by the user."))
        log(f"Manual step {i}: {s.title} ({s.start:.1f}s-{end:.1f}s)")
    final = shots / "99-final.png"
    run_ffmpeg(["-sseof", "-0.5", "-i", str(video), "-frames:v", "1", str(final)])

    env = EnvironmentRecord(
        app_name=req.manual_app_name or "unknown application",
        app_edition=capture.get("app_edition") or None,
        app_version=capture.get("app_version") or None,
        app_build=capture.get("app_build") or None,
        os=capture.get("os") or "unknown (manual capture)",
        platform=capture.get("platform") or "unknown (manual capture)",
        browser_name=capture.get("browser_name") or None,
        browser_version=capture.get("browser_version") or None,
        observed_ui_state="Reported by the user for a manual recording; not inspected automatically.",
        tested_at=capture.get("recorded_on") or capture["attested_at"],
    )
    log_path = project_dir / "runs" / run_id / "execution.log"
    log_path.write_text(f"Manual capture ingested on {platform.node()}\nRecording: {capture['video_path']} "
                        f"({duration:.1f}s, {vs['width']}x{vs['height']})\nAttested by user at {capture['attested_at']}\n")
    warnings: list[str] = []
    if not env.app_version:
        warnings.append("Application version not provided; recorded as unknown.")
    verification = VerificationRecord(
        workflow_id="manual", environment=env, outcome="passed", method="human_attested",
        checks=[Check(name="User attests the recording shows every step and the successful result", passed=True,
                      detail=f"attested at {capture['attested_at']}")],
        compatibility_warnings=warnings,
        evidence=[rel(p) for p in sorted(shots.glob("*.png"))] + [capture["video_path"], rel(log_path)])
    return ExecutionResult(run_id=run_id, workflow_id="manual", video_path=capture["video_path"], video_duration=duration,
                           viewport=(int(vs["width"]), int(vs["height"])), t_ready=0.0, steps=steps,
                           observations={}, log_path=rel(log_path), verification=verification)


def copy_into(project_dir: Path, source: Path) -> Path:
    """Place an existing local video file as the project's manual recording."""
    with open(source, "rb") as f:
        return save_upload(f, source.name, project_dir)

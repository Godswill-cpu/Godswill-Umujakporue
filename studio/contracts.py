"""Data contracts shared between pipeline modules.

Every stage reads and writes these models only; stages never reach into each
other's internals. All models serialise to JSON and are stored per project.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- request ---
class ManualStep(BaseModel):
    """A step marked by the user on their own recording (manual-capture fallback)."""
    start: float  # seconds into the uploaded recording
    title: str
    narration: str = ""
    expected: str = ""


class ProjectRequest(BaseModel):
    topic: str
    app_id: str
    workflow_id: str
    target_os: str = "Any (browser-based)"
    target_version: str = ""
    target_duration_s: int = 90
    voice: str = "en-US-AndrewNeural"
    speaking_rate: int = 0  # percent, -30..+30
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    resolution: Literal["1280x720", "1920x1080"] = "1920x1080"
    instructions: str = ""
    # Explicit opt-in to the robotic offline voice. Only honoured in development
    # mode; output is watermarked and can never pass the publishing gate.
    allow_dev_tts: bool = False
    pronunciations: dict[str, str] = Field(default_factory=dict)
    # "automated" = tested adapter drives the app; "manual" = user uploads their own recording.
    capture_mode: Literal["automated", "manual"] = "automated"
    manual_app_name: str = ""
    manual_steps: list[ManualStep] = Field(default_factory=list)
    # Documentation pages to research (fetched for real; claims must quote them verbatim).
    source_urls: list[str] = Field(default_factory=list)
    include_tips: bool = True

    @property
    def size(self) -> tuple[int, int]:
        w, h = self.resolution.split("x")
        return int(w), int(h)


# -------------------------------------------------------------- workflows ---
class Source(BaseModel):
    id: str
    title: str
    url: str = ""
    kind: Literal["official_docs", "bundled_test_app", "community", "other"]
    note: str = ""


class StepSpec(BaseModel):
    """One automatable action in a supported workflow (defined by an adapter)."""
    id: str
    title: str
    action: Literal["click", "check", "type", "wait"]
    selector: str | None = None
    value: str | None = None
    expected: str  # observable outcome the engine asserts after the action
    expect_selector: str | None = None  # element that must be visible afterwards
    narration: str  # factual narration template; {placeholders} filled from observations
    beginner_note: str = ""
    zoom: bool = False
    pause_after_ms: int = 1200
    source_ids: list[str] = Field(default_factory=list)


class WorkflowSpec(BaseModel):
    id: str
    app_id: str
    title: str
    summary: str
    prerequisites: list[str]
    steps: list[StepSpec]
    sources: list[Source]
    verification: str
    intro: str
    outro: str


# --------------------------------------------------------------- research ---
class ResearchDoc(BaseModel):
    id: str
    title: str
    url: str
    kind: Literal["official_docs", "bundled_test_app", "community", "other"]
    fetched_at: str
    sha256: str
    chars: int
    truncated: bool = False
    local_path: str  # project-relative copy of the extracted text


class ResearchFinding(BaseModel):
    id: str
    kind: Literal["prerequisite", "step_note", "troubleshooting", "version_note", "discrepancy"]
    claim: str
    source_id: str
    quote: str  # verified to occur verbatim (whitespace/case-normalised) in the fetched source
    step_id: str | None = None
    status: Literal["sourced"] = "sourced"  # sourced != demonstrated


class RejectedClaim(BaseModel):
    claim: str
    reason: str


class ResearchReport(BaseModel):
    provider: str
    model: str
    docs: list[ResearchDoc]
    findings: list[ResearchFinding]
    rejected: list[RejectedClaim] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    fetch_errors: list[str] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    created_at: str = Field(default_factory=now_iso)


# --------------------------------------------------------------- planning ---
class PlanStep(BaseModel):
    step_id: str
    title: str
    expected: str
    source_ids: list[str]
    status: Literal["planned", "verified", "failed", "skipped"] = "planned"


class TutorialPlan(BaseModel):
    workflow_id: str
    title: str
    summary: str
    prerequisites: list[str]
    steps: list[PlanStep]
    sources: list[Source]
    warnings: list[str] = Field(default_factory=list)
    generated_by: str
    research_note: str
    research: ResearchReport | None = None
    created_at: str = Field(default_factory=now_iso)


# ---------------------------------------------------------- demonstration ---
class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class EnvironmentRecord(BaseModel):
    app_name: str
    app_edition: str | None = None
    app_version: str | None = None  # None means explicitly unknown
    app_build: str | None = None
    os: str
    platform: str
    browser_name: str | None = None
    browser_version: str | None = None
    observed_ui_state: str = ""
    tested_at: str = Field(default_factory=now_iso)


class VerificationRecord(BaseModel):
    workflow_id: str
    environment: EnvironmentRecord
    outcome: Literal["passed", "failed", "unsupported"]
    # automated = adapter inspected real app state; human_attested = the user confirmed a manual recording.
    method: Literal["automated", "human_attested"] = "automated"
    checks: list[Check]
    compatibility_warnings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)  # project-relative paths
    verified_at: str = Field(default_factory=now_iso)


class StepResult(BaseModel):
    step_id: str
    title: str
    status: Literal["ok", "failed", "skipped"]
    t_start: float = 0.0  # seconds from start of recording
    t_end: float = 0.0
    screenshot: str | None = None
    target_box: dict | None = None  # {x,y,width,height} in viewport pixels
    message: str = ""


class ExecutionResult(BaseModel):
    run_id: str
    workflow_id: str
    video_path: str | None  # project-relative
    video_duration: float = 0.0
    viewport: tuple[int, int]
    t_ready: float = 0.0  # environment loaded and stable
    steps: list[StepResult]
    observations: dict = Field(default_factory=dict)
    log_path: str
    verification: VerificationRecord
    started_at: str = Field(default_factory=now_iso)


# ----------------------------------------------------------------- script ---
class ScriptSegment(BaseModel):
    id: str
    kind: Literal["intro", "step", "tip", "outro"]
    step_id: str | None = None
    finding_id: str | None = None  # for "tip": the sourced research finding it states
    text: str


class TutorialScript(BaseModel):
    run_id: str
    segments: list[ScriptSegment]
    edited: bool = False
    generated_by: str
    created_at: str = Field(default_factory=now_iso)


# -------------------------------------------------------------- narration ---
class WordTiming(BaseModel):
    text: str
    offset: float
    duration: float


class NarrationSegment(BaseModel):
    segment_id: str
    audio_path: str
    duration: float
    characters: int
    words: list[WordTiming] = Field(default_factory=list)
    cached: bool = False


class NarrationResult(BaseModel):
    provider: str
    production_grade: bool
    voice: str
    rate: int
    segments: list[NarrationSegment]
    total_duration: float
    approved: bool = False
    created_at: str = Field(default_factory=now_iso)


# ----------------------------------------------------------------- render ---
class Chapter(BaseModel):
    start: float
    title: str


class CaptionCue(BaseModel):
    start: float
    end: float
    text: str


class RenderResult(BaseModel):
    video_path: str
    srt_path: str
    audio_path: str
    duration: float
    resolution: str
    chapters: list[Chapter]
    cues: list[CaptionCue]
    dev_watermark: bool
    created_at: str = Field(default_factory=now_iso)


# --------------------------------------------------------------------- QC ---
class QCItem(BaseModel):
    id: str
    severity: Literal["blocker", "warning", "info"]
    category: str
    message: str
    automated: bool = True  # False => requires human judgement
    resolved: bool = False


class QCReport(BaseModel):
    items: list[QCItem]
    generated_at: str = Field(default_factory=now_iso)

    @property
    def blockers(self) -> list[QCItem]:
        return [i for i in self.items if i.severity == "blocker" and not i.resolved]


# ------------------------------------------------------------- publishing ---
class Approval(BaseModel):
    narration_approved_at: str | None = None
    version_limitation_acknowledged: bool = False
    final_approved_at: str | None = None
    notes: str = ""


class PublishingPackage(BaseModel):
    title: str
    description: str
    chapters_text: str
    tags: list[str]
    thumbnail_brief: str
    thumbnail_path: str | None = None
    export_zip: str | None = None
    created_at: str = Field(default_factory=now_iso)

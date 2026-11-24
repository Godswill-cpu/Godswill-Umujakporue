"""Stage orchestration: ordered, resumable stages run in a lightweight background thread."""
from __future__ import annotations

import logging
import threading
import traceback
from pathlib import Path

from . import planning, qc, scripting, video
from .config import Settings, redact
from .contracts import (Approval, Source, ExecutionResult, NarrationResult, QCReport, RenderResult, TutorialPlan,
                        TutorialScript)
from .db import STAGES, Database
from .registry import get_adapter, get_workflow

logger = logging.getLogger("studio.pipeline")

MODELS = {"plan": TutorialPlan, "execution": ExecutionResult, "script": TutorialScript,
          "narration": NarrationResult, "render": RenderResult, "qc": QCReport, "approval": Approval}
STAGE_OUTPUT = {"plan": "plan", "demonstrate": "execution", "script": "script", "narrate": "narration",
                "render": "render", "qc": "qc"}


class StageError(RuntimeError):
    pass


def workflow_for(req):
    if req.capture_mode == "manual":
        from .manual_capture import workflow_from_manual
        return workflow_from_manual(req)
    return get_workflow(req.app_id, req.workflow_id)


def load(project: dict, key: str):
    raw = project["state"].get(key)
    return MODELS[key].model_validate(raw) if raw is not None else None


class Pipeline:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        from .llm import select_llm
        from .research.sources import fetch
        self.llm_factory = select_llm  # replaceable in tests (labeled fakes only)
        self.fetcher = fetch

    def project_dir(self, pid: str) -> Path:
        d = self.settings.projects_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---------------------------------------------------------------- jobs
    def is_running(self, pid: str) -> bool:
        t = self._threads.get(pid)
        return bool(t and t.is_alive())

    def start(self, pid: str, from_stage: str | None = None, only: bool = False) -> bool:
        with self._lock:
            if self.is_running(pid):
                return False
            t = threading.Thread(target=self.run, args=(pid, from_stage, only), daemon=True, name=f"pipeline-{pid}")
            self._threads[pid] = t
            t.start()
            return True

    def wait(self, pid: str, timeout: float | None = None) -> None:
        t = self._threads.get(pid)
        if t:
            t.join(timeout)

    def first_incomplete(self, pid: str) -> str | None:
        stages = self.db.get_stages(pid)
        return next((s for s in STAGES if stages[s]["status"] != "done"), None)

    def invalidate_from(self, pid: str, stage: str) -> None:
        """Mark a stage and everything after it as pending; downstream approvals are revoked."""
        idx = STAGES.index(stage)
        for s in STAGES[idx:]:
            self.db.set_stage(pid, s, "pending")
            self.db.set_state(pid, STAGE_OUTPUT[s], None)
        self.db.set_state(pid, "publishing", None)
        approval = load(self.db.get_project(pid), "approval") or Approval()
        if idx <= STAGES.index("narrate"):
            approval.narration_approved_at = None
        approval.final_approved_at = None
        self.db.set_state(pid, "approval", approval)

    def run(self, pid: str, from_stage: str | None = None, only: bool = False) -> None:
        start = from_stage or self.first_incomplete(pid)
        if start is None:
            return
        if from_stage:
            self.invalidate_from(pid, from_stage)
        todo = [start] if only else STAGES[STAGES.index(start):]
        for stage in todo:
            self.db.set_stage(pid, stage, "running")
            self.db.log(pid, f"Stage '{stage}' started", stage=stage)
            try:
                getattr(self, f"stage_{stage}")(pid)
            except Exception as e:  # stop the pipeline; stage can be retried
                msg = redact(f"{e}", self.settings)
                logger.error("Stage %s failed for %s: %s\n%s", stage, pid, msg, redact(traceback.format_exc(), self.settings))
                self.db.set_stage(pid, stage, "failed", msg)
                self.db.log(pid, f"Stage '{stage}' failed: {msg}", level="error", stage=stage)
                return
            self.db.set_stage(pid, stage, "done")
            self.db.log(pid, f"Stage '{stage}' completed", stage=stage)

    # -------------------------------------------------------------- stages
    def _p(self, pid: str) -> dict:
        return self.db.get_project(pid)

    def _need(self, project: dict, key: str):
        val = load(project, key)
        if val is None:
            raise StageError(f"Required input '{key}' is missing; run the earlier stage first.")
        return val

    def stage_plan(self, pid: str) -> None:
        from .llm import select_llm
        from .llm.base import LLMError
        from .registry import get_app
        from .research.analyze import collect_urls, run_research
        p = self._p(pid)
        req = p["request"]
        plan = planning.build_plan(req)
        app = get_app(req.app_id)
        urls = collect_urls(req, app.doc_urls if app else [])
        if urls:
            llm = self.llm_factory(self.settings)
            if llm is None:
                plan.warnings.append("Documentation URLs were given, but no AI provider is configured (Settings), "
                                     "so no research was performed.")
            else:
                provider_key = f"llm:{llm.name}"
                left = self.settings.max_llm_tokens_per_project - self.db.billed_characters(pid, provider_key)
                try:
                    report = run_research(req, workflow_for(req), urls, self.project_dir(pid), self.settings.cache_dir,
                                          llm, left, fetcher=self.fetcher,
                                          log=lambda m: self.db.log(pid, m, stage="plan"))
                    self.db.record_usage(pid, provider_key, report.input_tokens + report.output_tokens, report.cached)
                    plan.research = report
                    plan.research_note = (f"Research by {report.provider} ({report.model}) on {len(report.docs)} fetched "
                                          f"source(s). Each finding's quote was checked verbatim against its source; "
                                          f"{len(report.rejected)} unsupported claim(s) were discarded. Findings are "
                                          "sourced, not demonstrated; the step sequence comes from the "
                                          + ("user's manual capture." if req.capture_mode == "manual" else "tested adapter workflow."))
                    plan.sources += [Source(
                        id=d.id, title=d.title, url=d.url, kind=d.kind, note=f"fetched {d.fetched_at}")
                        for d in report.docs]
                    for f in report.findings:
                        if f.kind == "discrepancy":
                            plan.warnings.append(f"Documentation differs from the tested workflow: {f.claim} [{f.source_id}]")
                    for st in plan.steps:
                        st.source_ids += [f.source_id for f in report.findings if f.step_id == st.step_id
                                          and f.source_id not in st.source_ids]
                except LLMError as e:
                    plan.warnings.append(f"Research failed: {redact(str(e), self.settings)}")
        self.db.set_state(pid, "plan", plan)
        for w in plan.warnings:
            self.db.log(pid, w, level="warning", stage="plan")

    def stage_demonstrate(self, pid: str) -> None:
        p = self._p(pid)
        req = p["request"]
        plan = self._need(p, "plan")
        if req.capture_mode == "manual":
            from .manual_capture import ingest
            result = ingest(self.project_dir(pid), req, p["state"].get("manual_capture") or {},
                            log=lambda m: self.db.log(pid, m, stage="demonstrate"))
            for s in plan.steps:
                s.status = "verified"
            self.db.set_state(pid, "plan", plan)
            self.db.set_state(pid, "execution", result)
            return
        from .demo_engine import run_demonstration
        adapter = get_adapter(req.app_id)
        wf = get_workflow(req.app_id, req.workflow_id)
        result = run_demonstration(adapter, wf, self.project_dir(pid), req.size,
                                   chromium_executable=self.settings.chromium_executable,
                                   headless=self.settings.browser_headless,
                                   log=lambda m: self.db.log(pid, m, stage="demonstrate"))
        status = {r.step_id: r.status for r in result.steps}
        for s in plan.steps:
            s.status = {"ok": "verified" if result.verification.outcome == "passed" else "planned",
                        "failed": "failed", "skipped": "skipped"}[status.get(s.step_id, "skipped")]
        self.db.set_state(pid, "plan", plan)
        self.db.set_state(pid, "execution", result)
        if result.verification.outcome != "passed":
            raise StageError("Demonstration did not pass verification. See the Demonstration Manager for evidence.")

    def stage_script(self, pid: str) -> None:
        p = self._p(pid)
        req = p["request"]
        execution = self._need(p, "execution")
        script = scripting.generate_script(req, workflow_for(req), execution, load(p, "plan"))
        est = scripting.estimate_seconds(script, req.speaking_rate)
        self.db.log(pid, f"Script: {len(script.segments)} segments, estimated narration {est:.0f}s "
                         f"(target video {req.target_duration_s}s)", stage="script")
        self.db.set_state(pid, "script", script)

    def stage_narrate(self, pid: str) -> None:
        from .narration import narrate, select_provider
        p = self._p(pid)
        req = p["request"]
        script = self._need(p, "script")
        provider = select_provider(self.settings, req, log=lambda m: self.db.log(pid, m, level="warning", stage="narrate"))
        if not provider.production_grade:
            self.db.log(pid, "Using the ROBOTIC DEVELOPMENT VOICE (explicitly enabled). Output cannot be published.",
                        level="warning", stage="narrate")
        result = narrate(self.settings, req, script, self.project_dir(pid) / "narration", provider,
                         usage=lambda prov, n, cached: self.db.record_usage(pid, prov, n, cached),
                         billed_so_far=self.db.billed_characters(pid, provider.name),
                         log=lambda m: self.db.log(pid, m, stage="narrate"))
        self.db.set_state(pid, "narration", result)

    def build_scenes(self, req, execution: ExecutionResult, script: TutorialScript, narration: NarrationResult) -> list[video.Scene]:
        wf = workflow_for(req)
        specs = {s.id: s for s in wf.steps}
        steps = [s for s in execution.steps if s.status == "ok"]
        by_step = {s.step_id: s for s in steps}
        audio = {n.segment_id: n for n in narration.segments}
        scenes = []
        for seg in script.segments:
            n = audio[seg.id]
            if seg.kind == "intro":
                a, b, title, box, callout = execution.t_ready, (steps[0].t_start if steps else execution.video_duration), "Overview", None, None
            elif seg.kind in ("outro", "tip"):
                # the verified final state stays on screen
                a = steps[-1].t_end if steps else execution.t_ready
                b, box = execution.video_duration, None
                title, callout = ("Result", "Result verified") if seg.kind == "outro" else ("Tip", "Tip from the documentation")
            else:
                r = by_step[seg.step_id]
                i = steps.index(r)
                a = r.t_start
                b = steps[i + 1].t_start if i + 1 < len(steps) else r.t_end
                title = r.title
                box = r.target_box if specs[r.step_id].zoom else None
                callout = f"Step {i + 1}: {r.title}"
            b = min(b, execution.video_duration)
            scenes.append(video.Scene(id=seg.id, title=title, src_start=max(0.0, a), src_end=max(a + 0.1, b),
                                      audio=Path(n.audio_path), audio_duration=n.duration, text=seg.text,
                                      zoom_box=box, callout=callout, words=[w.model_dump() for w in n.words]))
        return scenes

    def stage_render(self, pid: str) -> None:
        p = self._p(pid)
        req = p["request"]
        execution = self._need(p, "execution")
        script = self._need(p, "script")
        narration = self._need(p, "narration")
        if execution.verification.outcome != "passed":
            raise StageError("Refusing to render a tutorial from an unverified demonstration.")
        plan = self._need(p, "plan")
        pdir = self.project_dir(pid)
        scenes = self.build_scenes(req, execution, script, narration)
        env = execution.verification.environment
        subtitle = f"{env.app_name} {env.app_version or ''}".strip()
        result = video.assemble(pdir / execution.video_path, scenes, pdir / "render", plan.title, subtitle,
                                tuple(execution.viewport), req.size, dev_watermark=not narration.production_grade,
                                log=lambda m: self.db.log(pid, m, stage="render"))
        self.db.set_state(pid, "render", result)

    def stage_qc(self, pid: str) -> None:
        p = self._p(pid)
        report = qc.run_qc(self.project_dir(pid), p["request"], load(p, "plan"), load(p, "execution"),
                           load(p, "script"), load(p, "narration"), load(p, "render"))
        self.db.set_state(pid, "qc", report)
        self.db.log(pid, f"QC: {len(report.blockers)} blocker(s), "
                         f"{sum(1 for i in report.items if i.severity == 'warning')} warning(s)", stage="qc")

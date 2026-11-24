"""FastAPI application: dashboard pages and JSON API."""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, metrics, planning, publishing
from ..config import Settings, load_settings, save_preferences, save_secret
from ..contracts import Approval, ProjectRequest, ReverificationRecord, TutorialScript, now_iso
from ..db import STAGES, Database
from ..pipeline import Pipeline, load, workflow_for
from ..manual_capture import ManualCaptureError, parse_steps, save_upload, steps_to_text
from ..registry import APPS, get_app, get_workflow, supported_workflows

HERE = Path(__file__).resolve().parent
STAGE_LABELS = {"plan": "Research & planning", "demonstrate": "Verified demonstration", "script": "Script",
                "narrate": "Narration", "render": "Video assembly", "qc": "Quality control"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(settings.data_dir / "studio.log")])
    db = Database(settings.db_path)
    for pid_, stage_ in db.recover_interrupted():
        logging.getLogger("studio").warning("Recovered interrupted stage %s of project %s", stage_, pid_)
    pipe = Pipeline(settings, db)
    app = FastAPI(title="Automated Software Tutorial Studio", version=__version__)
    app.state.settings, app.state.db, app.state.pipeline = settings, db, pipe
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=HERE / "templates")

    def rel(pid: str, path: str | None) -> str | None:
        if not path:
            return None
        p = Path(path)
        base = settings.projects_dir / pid
        try:
            return str(p.resolve().relative_to(base.resolve())) if p.is_absolute() else str(p)
        except ValueError:
            return None

    tpl.env.globals.update(stage_labels=STAGE_LABELS, stages=STAGES, version=__version__, mode=lambda: settings.mode)
    tpl.env.filters["mmss"] = lambda t: f"{int(t)//60}:{int(t)%60:02d}"

    def page(request: Request, name: str, **ctx):
        return tpl.TemplateResponse(request, name, {"settings": settings, **ctx})

    def project_or_404(pid: str) -> dict:
        p = db.get_project(pid)
        if not p:
            raise HTTPException(404, "Project not found")
        return p

    def _baseline(raw: str) -> int | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        if not raw.isdigit() or not 1 <= int(raw) <= 100000:
            raise HTTPException(400, "Manual baseline must be a whole number of minutes.")
        return int(raw)

    def summarize(p: dict) -> dict:
        st = p["stages"]
        if pipe.is_running(p["id"]) or any(s["status"] == "running" for s in st.values()):
            status = "running"
        elif any(s["status"] == "failed" for s in st.values()):
            status = "failed"
        elif (p["state"].get("approval") or {}).get("final_approved_at"):
            status = "approved"
        elif all(s["status"] == "done" for s in st.values()):
            status = "ready for review"
        elif all(s["status"] == "pending" for s in st.values()):
            status = "new"
        else:
            status = "in progress"
        return {**p, "status": status}

    # ------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        projects = [summarize(p) for p in db.list_projects()]
        counts = {k: sum(1 for p in projects if p["status"] == k) for k in
                  ("running", "failed", "ready for review", "approved", "in progress", "new")}
        recent = [p for p in projects if p["state"].get("render")][:5]
        return page(request, "dashboard.html", projects=projects, counts=counts, recent=recent,
                    portfolio=metrics.portfolio_metrics(db, projects))

    @app.get("/create", response_class=HTMLResponse)
    def create_form(request: Request, workflow: str | None = None):
        return page(request, "create.html", apps=APPS, workflows=supported_workflows(), selected=workflow,
                    voices=__import__("studio.tts.azure", fromlist=["AZURE_VOICES"]).AZURE_VOICES,
                    discovered=planning.discover_topics())

    @app.post("/create")
    def create(request: Request, topic: str = Form(...), workflow_id: str = Form(""), capture_mode: str = Form("automated"),
               manual_app_name: str = Form(""),
               target_os: str = Form("Any (browser-based)"), target_version: str = Form(""),
               target_duration_s: int = Form(90), voice: str = Form("en-US-AndrewNeural"),
               speaking_rate: int = Form(0), difficulty: str = Form("beginner"), resolution: str = Form("1920x1080"),
               instructions: str = Form(""), allow_dev_tts: bool = Form(False), start: bool = Form(False),
               source_urls: str = Form(""), include_tips: bool = Form(False),
               manual_baseline_minutes: str = Form("")):
        urls = [u.strip() for u in source_urls.splitlines() if u.strip()]
        bad = [u for u in urls if not u.startswith("https://")]
        if bad:
            raise HTTPException(400, f"Documentation URLs must start with https://: {bad[0]}")
        if capture_mode == "manual":
            if not topic.strip() or not manual_app_name.strip():
                raise HTTPException(400, "Manual capture needs a topic and the application name.")
            app_id, wf_id, default_title = "manual", "manual", topic.strip()
        else:
            wf = next((w for w in supported_workflows() if w.id == workflow_id), None)
            if not wf:
                raise HTTPException(400, "Choose a supported workflow, or use manual capture. "
                                         "Unsupported applications cannot be automated.")
            app_id, wf_id, default_title = wf.app_id, wf.id, wf.title
        req = ProjectRequest(topic=topic.strip() or default_title, app_id=app_id, workflow_id=wf_id,
                             capture_mode="manual" if capture_mode == "manual" else "automated",
                             manual_app_name=manual_app_name.strip()[:120], target_os=target_os,
                             target_version=target_version.strip(), target_duration_s=max(15, min(target_duration_s, 1800)),
                             voice=voice, speaking_rate=max(-30, min(speaking_rate, 30)), difficulty=difficulty,
                             resolution=resolution, instructions=instructions,
                             allow_dev_tts=bool(allow_dev_tts) and settings.mode == "development",
                             source_urls=urls[:8], include_tips=bool(include_tips),
                             manual_baseline_minutes=_baseline(manual_baseline_minutes))
        pid = db.create_project(req.topic, req)
        db.log(pid, f"Project created ({req.capture_mode} capture, workflow {wf_id})")
        db.record_intervention(pid, "create project")
        if start and req.capture_mode == "manual":
            pipe.start(pid, only=True)  # plan only; the rest waits for the upload
        elif start:
            pipe.start(pid)
        return RedirectResponse(f"/projects/{pid}", status_code=303)

    @app.get("/projects/{pid}", response_class=HTMLResponse)
    def project_page(request: Request, pid: str):
        p = summarize(project_or_404(pid))
        st = {k: load(p, k) for k in ("plan", "execution", "script", "narration", "render", "qc")}
        approval = load(p, "approval") or Approval()
        gate = publishing.check_gate(st["execution"], st["narration"], st["render"], st["qc"], approval)
        meta = None
        if st["render"] and st["execution"] and st["plan"] and st["script"]:
            meta = publishing.build_metadata(st["plan"], st["execution"], st["render"], st["script"])
        from ..narration import select_provider
        try:
            prov = select_provider(settings, p["request"])
            voices, provider_error = prov.voices(), None
            provider_name, provider_prod = prov.name, prov.production_grade
        except Exception as e:
            voices, provider_error, provider_name, provider_prod = [], str(e), None, False
        return page(request, "project.html", p=p, **st, approval=approval, gate=gate, meta=meta,
                    rel=lambda path: rel(pid, path), events=db.events(pid), running=pipe.is_running(pid),
                    voices=voices, provider_error=provider_error, provider_name=provider_name,
                    provider_prod=provider_prod, publishing_pkg=p["state"].get("publishing"),
                    workflow=workflow_for(p["request"]), m=metrics.project_metrics(db, p),
                    reverifications=[ReverificationRecord.model_validate(r)
                                     for r in reversed(p["state"].get("reverifications") or [])], manual=p["state"].get("manual_capture") or {},
                    manual_steps_text=steps_to_text(p["request"].manual_steps))

    @app.get("/api/projects/{pid}/status")
    def status(pid: str):
        p = summarize(project_or_404(pid))
        return {"status": p["status"], "running": pipe.is_running(pid),
                "stages": {k: {"status": v["status"], "error": v["error"]} for k, v in p["stages"].items()},
                "events": db.events(pid, 15)}

    @app.post("/projects/{pid}/run")
    def run(pid: str, from_stage: str = Form(""), only: bool = Form(False)):
        project_or_404(pid)
        if from_stage and from_stage not in STAGES:
            raise HTTPException(400, "Unknown stage")
        if not pipe.start(pid, from_stage or None, only):
            raise HTTPException(409, "A job is already running for this project")
        db.record_intervention(pid, f"re-run from {from_stage}" if from_stage else "run / resume pipeline")
        return RedirectResponse(f"/projects/{pid}#pipeline", status_code=303)

    @app.post("/api/projects/{pid}/activity")
    def activity(pid: str, seconds: float = Form(...)):
        project_or_404(pid)
        db.record_active(pid, seconds)
        return {"ok": True}

    @app.post("/projects/{pid}/baseline")
    def set_baseline(pid: str, manual_baseline_minutes: str = Form("")):
        p = project_or_404(pid)
        db.update_request(pid, p["request"].model_copy(update={"manual_baseline_minutes": _baseline(manual_baseline_minutes)}))
        return RedirectResponse(f"/projects/{pid}#metrics", status_code=303)

    @app.post("/projects/{pid}/stop")
    def stop(pid: str):
        project_or_404(pid)
        if not pipe.request_stop(pid):
            raise HTTPException(409, "No job is running for this project.")
        db.log(pid, "Stop requested: the current stage will finish, then the pipeline stops", level="warning")
        return RedirectResponse(f"/projects/{pid}#pipeline", status_code=303)

    @app.post("/projects/{pid}/reverify")
    def reverify(pid: str):
        p = project_or_404(pid)
        if not load(p, "execution"):
            raise HTTPException(400, "This project has no demonstration to re-verify.")
        if p["request"].capture_mode == "manual":
            raise HTTPException(400, "Manual-capture tutorials cannot be re-verified automatically.")
        if not pipe.start_reverify(pid):
            raise HTTPException(409, "A job is already running for this project")
        db.record_intervention(pid, "re-verification")
        return RedirectResponse(f"/projects/{pid}#demo", status_code=303)

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request):
        rows = []
        for p in db.list_projects():
            for stage, st in p["stages"].items():
                if st["status"] in ("running", "failed"):
                    rows.append({"p": p, "stage": stage, "st": st, "running": pipe.is_running(p["id"])})
        rows.sort(key=lambda r: (r["st"]["status"] != "running", r["st"]["started_at"] or ""), reverse=False)
        return page(request, "jobs.html", rows=rows)

    @app.post("/projects/{pid}/manual-capture")
    def manual_capture(pid: str, recording: UploadFile | None = File(None), steps: str = Form(""),
                       app_version: str = Form(""), app_edition: str = Form(""), app_build: str = Form(""),
                       os_name: str = Form(""), platform_name: str = Form(""), browser_name: str = Form(""),
                       browser_version: str = Form(""), recorded_on: str = Form(""), attest: bool = Form(False)):
        p = project_or_404(pid)
        req: ProjectRequest = p["request"]
        if req.capture_mode != "manual":
            raise HTTPException(400, "This project uses automated capture.")
        if pipe.is_running(pid):
            raise HTTPException(409, "A job is already running for this project")
        cap = dict(p["state"].get("manual_capture") or {})
        pdir = pipe.project_dir(pid)
        changed = False
        try:
            if recording is not None and recording.filename:
                dest = save_upload(recording.file, recording.filename, pdir)
                cap["video_path"] = str(dest.relative_to(pdir))
                changed = True
                db.log(pid, f"Manual recording uploaded: {recording.filename}", stage="demonstrate")
            db.record_intervention(pid, "manual capture upload")
            if steps.strip():
                new_steps = parse_steps(steps)
                if new_steps != req.manual_steps:
                    req = req.model_copy(update={"manual_steps": new_steps})
                    db.update_request(pid, req)
                    changed = True
        except ManualCaptureError as e:
            raise HTTPException(400, str(e))
        env = {"app_version": app_version, "app_edition": app_edition, "app_build": app_build, "os": os_name,
               "platform": platform_name, "browser_name": browser_name, "browser_version": browser_version,
               "recorded_on": recorded_on}
        if any((cap.get(k) or "") != v.strip() for k, v in env.items()):
            changed = True
        cap.update({k: v.strip()[:200] for k, v in env.items()})
        if changed:
            cap.pop("attested_at", None)  # any change requires a fresh attestation
        if attest:
            if not cap.get("video_path") or not req.manual_steps:
                raise HTTPException(400, "Upload a recording and mark the steps before confirming.")
            cap["attested_at"] = now_iso()
            db.log(pid, "User attested that the manual recording shows every step succeeding", stage="demonstrate")
            db.record_intervention(pid, "manual capture attestation")
        db.set_state(pid, "manual_capture", cap)
        if cap.get("attested_at"):
            pipe.start(pid, "plan")  # re-plan from the marked steps, then ingest and continue
        elif changed:
            pipe.invalidate_from(pid, "demonstrate")
        return RedirectResponse(f"/projects/{pid}#demo", status_code=303)

    @app.post("/projects/{pid}/script")
    async def save_script(request: Request, pid: str):
        p = project_or_404(pid)
        script = load(p, "script")
        if not script:
            raise HTTPException(400, "No script yet")
        form = await request.form()
        changed = False
        for seg in script.segments:
            new = str(form.get(f"seg-{seg.id}", seg.text)).strip()
            if new and new != seg.text:
                seg.text, changed = new, True
        if changed:
            script.edited = True
            pipe.invalidate_from(pid, "narrate")
            db.set_state(pid, "script", script)
            db.log(pid, "Script edited by user; narration, render and QC must be regenerated", stage="script")
            db.record_intervention(pid, "script edit")
        return RedirectResponse(f"/projects/{pid}#script", status_code=303)

    @app.post("/projects/{pid}/voice")
    def save_voice(pid: str, voice: str = Form(...), speaking_rate: int = Form(0), pronunciations: str = Form(""),
                   allow_dev_tts: bool = Form(False)):
        p = project_or_404(pid)
        req: ProjectRequest = p["request"]
        pron = {}
        for line in pronunciations.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                if k.strip() and v.strip():
                    pron[k.strip()] = v.strip()
        req = req.model_copy(update={"voice": voice, "speaking_rate": max(-30, min(speaking_rate, 30)),
                                     "pronunciations": pron,
                                     "allow_dev_tts": bool(allow_dev_tts) and settings.mode == "development"})
        db.update_request(pid, req)
        if db.get_stages(pid)["narrate"]["status"] == "done":
            pipe.invalidate_from(pid, "narrate")
        db.log(pid, f"Voice settings changed: {voice}, rate {req.speaking_rate:+d}%, {len(pron)} pronunciation(s)")
        db.record_intervention(pid, "voice settings change")
        return RedirectResponse(f"/projects/{pid}#voice", status_code=303)

    @app.post("/projects/{pid}/voice-preview")
    def voice_preview(pid: str, text: str = Form("This is a preview of the narration voice.")):
        from ..narration import select_provider
        p = project_or_404(pid)
        req = p["request"]
        try:
            prov = select_provider(settings, req)
            out = Path(tempfile.mkdtemp(dir=settings.cache_dir if settings.cache_dir.exists() else None)) / "preview.wav"
            if prov.production_grade and db.billed_characters(pid, prov.name) + len(text) > settings.max_tts_chars_per_project:
                raise RuntimeError("TTS character limit reached for this project")
            prov.synthesize(text[:400], req.voice if prov.production_grade else "slt", req.speaking_rate,
                            req.pronunciations, out)
            db.record_usage(pid, prov.name, len(text[:400]), False)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return FileResponse(out, media_type="audio/wav")

    @app.post("/projects/{pid}/approve-narration")
    def approve_narration(pid: str):
        p = project_or_404(pid)
        narration = load(p, "narration")
        if not narration:
            raise HTTPException(400, "No narration to approve")
        if not narration.production_grade:
            raise HTTPException(400, "Development-voice narration cannot be approved for publication.")
        approval = load(p, "approval") or Approval()
        approval.narration_approved_at = now_iso()
        db.set_state(pid, "approval", approval)
        db.log(pid, "Narration approved by user")
        db.record_intervention(pid, "narration approval")
        return RedirectResponse(f"/projects/{pid}#voice", status_code=303)

    @app.post("/projects/{pid}/ack-version")
    def ack_version(pid: str):
        p = project_or_404(pid)
        approval = load(p, "approval") or Approval()
        approval.version_limitation_acknowledged = True
        db.set_state(pid, "approval", approval)
        db.log(pid, "User acknowledged unknown-version limitation")
        db.record_intervention(pid, "version acknowledgement")
        return RedirectResponse(f"/projects/{pid}#qc", status_code=303)

    def _gate(p):
        st = {k: load(p, k) for k in ("execution", "narration", "render", "qc")}
        return publishing.check_gate(st["execution"], st["narration"], st["render"], st["qc"], load(p, "approval") or Approval())

    @app.post("/projects/{pid}/approve")
    def approve(pid: str, confirm: bool = Form(False), notes: str = Form("")):
        p = project_or_404(pid)
        reasons = _gate(p)
        if reasons:
            db.log(pid, "Final approval refused: " + " | ".join(reasons), level="warning")
            raise HTTPException(409, "Cannot approve: " + " ".join(reasons))
        if not confirm:
            raise HTTPException(400, "Tick the confirmation box: you watched the full video and authorize export.")
        approval = load(p, "approval") or Approval()
        approval.final_approved_at, approval.notes = now_iso(), notes[:1000]
        db.set_state(pid, "approval", approval)
        db.log(pid, "Final approval granted by user")
        db.record_intervention(pid, "final approval")
        return RedirectResponse(f"/projects/{pid}#publishing", status_code=303)

    @app.post("/projects/{pid}/export")
    def export(pid: str):
        p = project_or_404(pid)
        approval = load(p, "approval") or Approval()
        reasons = _gate(p)
        if reasons or not approval.final_approved_at:
            raise HTTPException(409, "Export requires a passed gate and final human approval. " + " ".join(reasons))
        plan, execution, render, script = (load(p, k) for k in ("plan", "execution", "render", "script"))
        pkg = publishing.build_metadata(plan, execution, render, script)
        pdir = pipe.project_dir(pid)
        final_shot = next((pdir / s for s in reversed(execution.verification.evidence) if s.endswith("99-final.png")), None)
        if final_shot and final_shot.exists():
            publishing.make_thumbnail(final_shot, plan.title, pdir / "thumbnail.png")
            pkg.thumbnail_path = "thumbnail.png"
        z = publishing.export_package(pdir, pkg, render, execution, load(p, "qc"), load(p, "narration"), approval)
        pkg.export_zip = str(z.relative_to(pdir))
        db.set_state(pid, "publishing", pkg)
        db.log(pid, "Export package created (no upload performed)")
        db.record_intervention(pid, "export")
        return RedirectResponse(f"/projects/{pid}#publishing", status_code=303)

    @app.get("/media/{pid}/{path:path}")
    def media(pid: str, path: str):
        base = (settings.projects_dir / pid).resolve()
        target = (base / path).resolve()
        if base not in target.parents or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target)

    @app.get("/registry", response_class=HTMLResponse)
    def registry_page(request: Request):
        retest = []
        for p in db.list_projects():
            ex = load(p, "execution")
            if not ex:
                continue
            history = p["state"].get("reverifications") or []
            last = ReverificationRecord.model_validate(history[-1]) if history else None
            if last and last.outcome != "passed":
                retest.append({"p": p, "env": last.environment, "age": 0, "reason": "re-verification FAILED: workflow no longer works"})
                continue
            if last and last.changes:
                retest.append({"p": p, "env": last.environment, "age": 0,
                               "reason": "still works, but environment changed: " + "; ".join(last.changes)})
                continue
            env = last.environment if last else ex.verification.environment
            app_entry = get_app(p["request"].app_id)
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(env.tested_at)).days
            outdated = app_entry and env.app_version and not any(env.app_version in v for v in app_entry.tested_versions)
            if age > 90 or outdated or not env.app_version:
                retest.append({"p": p, "env": env, "age": age,
                               "reason": "version no longer in tested list" if outdated else
                               ("version unknown" if not env.app_version else f"tested {age} days ago")})
        return page(request, "registry.html", apps=APPS, workflows=supported_workflows(), retest=retest)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: bool = False):
        return page(request, "settings.html", info=settings.public_dict(), saved=saved)

    @app.post("/settings")
    def save_settings(azure_key: str = Form(""), azure_region: str = Form(""), clear_key: bool = Form(False),
                      max_chars: int = Form(20000), mode: str = Form("development"),
                      llm_provider: str = Form("none"), anthropic_key: str = Form(""), clear_anthropic_key: bool = Form(False),
                      llm_model: str = Form("claude-opus-5-5"), max_llm_tokens: int = Form(300000)):
        if clear_key:
            save_secret(settings.data_dir, "AZURE_SPEECH_KEY", "")
        elif azure_key.strip():
            save_secret(settings.data_dir, "AZURE_SPEECH_KEY", azure_key.strip())
        if clear_anthropic_key:
            save_secret(settings.data_dir, "ANTHROPIC_API_KEY", "")
        elif anthropic_key.strip():
            save_secret(settings.data_dir, "ANTHROPIC_API_KEY", anthropic_key.strip())
        prefs = {"STUDIO_MAX_TTS_CHARS_PER_PROJECT": max(0, max_chars), "STUDIO_MODE": mode,
                 "STUDIO_LLM_PROVIDER": llm_provider if llm_provider in ("none", "anthropic") else "none",
                 "STUDIO_LLM_MODEL": llm_model.strip() or "claude-opus-5-5",
                 "STUDIO_MAX_LLM_TOKENS_PER_PROJECT": max(0, max_llm_tokens)}
        if azure_region.strip():
            prefs["AZURE_SPEECH_REGION"] = azure_region.strip()
        save_preferences(settings.data_dir, prefs)
        fresh = load_settings({**__import__("os").environ, "STUDIO_DATA_DIR": str(settings.data_dir)})
        for field in ("azure_speech_key", "azure_speech_region", "max_tts_chars_per_project", "mode", "llm_provider",
                      "anthropic_api_key", "llm_model", "max_llm_tokens_per_project"):
            setattr(settings, field, getattr(fresh, field))
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "mode": settings.mode}

    return app

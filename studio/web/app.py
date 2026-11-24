"""FastAPI application: dashboard pages and JSON API."""
from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, planning, publishing
from ..config import Settings, load_settings, save_preferences, save_secret
from ..contracts import Approval, ProjectRequest, TutorialScript, now_iso
from ..db import STAGES, Database
from ..pipeline import Pipeline, load
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
        return page(request, "dashboard.html", projects=projects, counts=counts, recent=recent)

    @app.get("/create", response_class=HTMLResponse)
    def create_form(request: Request, workflow: str | None = None):
        return page(request, "create.html", apps=APPS, workflows=supported_workflows(), selected=workflow,
                    voices=__import__("studio.tts.azure", fromlist=["AZURE_VOICES"]).AZURE_VOICES,
                    discovered=planning.discover_topics())

    @app.post("/create")
    def create(request: Request, topic: str = Form(...), workflow_id: str = Form(...),
               target_os: str = Form("Any (browser-based)"), target_version: str = Form(""),
               target_duration_s: int = Form(90), voice: str = Form("en-US-AndrewNeural"),
               speaking_rate: int = Form(0), difficulty: str = Form("beginner"), resolution: str = Form("1920x1080"),
               instructions: str = Form(""), allow_dev_tts: bool = Form(False), start: bool = Form(False)):
        wf = next((w for w in supported_workflows() if w.id == workflow_id), None)
        if not wf:
            raise HTTPException(400, "Choose a supported workflow. Unsupported applications cannot be automated.")
        req = ProjectRequest(topic=topic.strip() or wf.title, app_id=wf.app_id, workflow_id=wf.id, target_os=target_os,
                             target_version=target_version.strip(), target_duration_s=max(15, min(target_duration_s, 1800)),
                             voice=voice, speaking_rate=max(-30, min(speaking_rate, 30)), difficulty=difficulty,
                             resolution=resolution, instructions=instructions,
                             allow_dev_tts=bool(allow_dev_tts) and settings.mode == "development")
        pid = db.create_project(req.topic, req)
        db.log(pid, f"Project created for workflow {wf.id}")
        if start:
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
                    workflow=get_workflow(p["request"].app_id, p["request"].workflow_id))

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
        return RedirectResponse(f"/projects/{pid}#pipeline", status_code=303)

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
        return RedirectResponse(f"/projects/{pid}#voice", status_code=303)

    @app.post("/projects/{pid}/ack-version")
    def ack_version(pid: str):
        p = project_or_404(pid)
        approval = load(p, "approval") or Approval()
        approval.version_limitation_acknowledged = True
        db.set_state(pid, "approval", approval)
        db.log(pid, "User acknowledged unknown-version limitation")
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
            env = ex.verification.environment
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
                      max_chars: int = Form(20000), mode: str = Form("development")):
        if clear_key:
            save_secret(settings.data_dir, "AZURE_SPEECH_KEY", "")
        elif azure_key.strip():
            save_secret(settings.data_dir, "AZURE_SPEECH_KEY", azure_key.strip())
        prefs = {"STUDIO_MAX_TTS_CHARS_PER_PROJECT": max(0, max_chars), "STUDIO_MODE": mode}
        if azure_region.strip():
            prefs["AZURE_SPEECH_REGION"] = azure_region.strip()
        save_preferences(settings.data_dir, prefs)
        fresh = load_settings({**__import__("os").environ, "STUDIO_DATA_DIR": str(settings.data_dir)})
        for field in ("azure_speech_key", "azure_speech_region", "max_tts_chars_per_project", "mode"):
            setattr(settings, field, getattr(fresh, field))
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "mode": settings.mode}

    return app

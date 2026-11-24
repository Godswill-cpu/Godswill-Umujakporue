"""Stage 3: verified software demonstration with Playwright.

Runs a tested workflow inside an isolated environment, records real video of
the browser, captures screenshots, asserts each step's expected outcome and
asks the adapter to verify the end state. On any unexpected behaviour the run
stops immediately instead of improvising.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from .contracts import Check, ExecutionResult, StepResult, VerificationRecord, WorkflowSpec
from .media import probe_duration

# Visible cursor + click ripple. Headless Chromium draws no OS cursor, so the
# page renders one that follows real Playwright mouse events.
CURSOR_JS = r"""
(() => {
  if (window.__studioCursor) return; window.__studioCursor = true;
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;' +
    'background:rgba(255,196,0,.35);border:2px solid rgba(230,120,0,.95);z-index:2147483647;pointer-events:none;' +
    'transition:transform .12s;transform:translate(-100px,-100px)';
  const add = () => document.body.appendChild(c);
  document.body ? add() : document.addEventListener('DOMContentLoaded', add);
  let x=-100, y=-100;
  document.addEventListener('mousemove', e => { x=e.clientX; y=e.clientY; c.style.transform = `translate(${x}px,${y}px)`; }, true);
  document.addEventListener('mousedown', () => {
    c.style.transform = `translate(${x}px,${y}px) scale(.7)`;
    const r = document.createElement('div');
    r.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;` +
      'border:3px solid rgba(230,120,0,.9);z-index:2147483646;pointer-events:none;transition:all .45s ease-out;opacity:1';
    document.body.appendChild(r);
    requestAnimationFrame(() => { r.style.width='60px'; r.style.height='60px'; r.style.margin='-30px 0 0 -30px'; r.style.opacity='0'; });
    setTimeout(() => r.remove(), 600);
  }, true);
  document.addEventListener('mouseup', () => { c.style.transform = `translate(${x}px,${y}px)`; }, true);
})();
"""


class DemoAborted(Exception):
    pass


def run_demonstration(adapter, workflow: WorkflowSpec, project_dir: Path, viewport: tuple[int, int],
                      chromium_executable: str | None = None, headless: bool = True, log=print) -> ExecutionResult:
    from playwright.sync_api import sync_playwright

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    run_dir = project_dir / "runs" / run_id
    shots = run_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []

    def note(msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        log_lines.append(line)
        log(msg)

    rel = lambda p: str(Path(p).relative_to(project_dir))
    results: list[StepResult] = []
    observations: dict = {}
    checks: list[Check] = []
    warnings: list[str] = []
    env_record = None
    outcome = "failed"
    t_ready = 0.0
    w, h = viewport

    with sync_playwright() as p:
        launch = {"headless": headless}
        if chromium_executable:
            launch["executable_path"] = chromium_executable
        browser = p.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": w, "height": h}, record_video_dir=str(run_dir / "raw"),
                                      record_video_size={"width": w, "height": h}, device_scale_factor=1)
        allowed = adapter.allowed_url_prefixes()

        def guard(route):
            url = route.request.url
            if any(url.startswith(a) for a in allowed) or url.startswith("data:"):
                route.continue_()
            else:
                note(f"BLOCKED network request outside test environment: {url}")
                route.abort()

        context.route("**/*", guard)
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        t0 = time.monotonic()
        clock = lambda: round(time.monotonic() - t0, 3)
        try:
            note(f"Opening isolated test environment {adapter.environment_url()}")
            page.goto(adapter.environment_url())
            adapter.wait_ready(page)
            env_record = adapter.detect_environment(page, browser)
            note(f"Detected {env_record.app_name} {env_record.app_version or 'version unknown'} "
                 f"(build {env_record.app_build or 'unknown'}), browser {env_record.browser_name} {env_record.browser_version}")

            # Compatibility: every control the workflow needs must exist in this environment.
            for s in workflow.steps:
                if s.selector and page.locator(s.selector).count() == 0:
                    warnings.append(f"Missing control for step '{s.title}': {s.selector}")
            if warnings:
                raise DemoAborted("Interface does not match the tested workflow: " + "; ".join(warnings))

            observations = adapter.observe_before(page, workflow)
            note(f"Observed initial state: {json.dumps({k: v for k, v in observations.items() if not k.endswith('_table')})}")
            page.mouse.move(w * 0.55, h * 0.6)
            page.wait_for_timeout(1500)
            t_ready = clock()
            page.screenshot(path=str(shots / "00-ready.png"))

            for i, s in enumerate(workflow.steps, 1):
                r = StepResult(step_id=s.id, title=s.title, status="failed", t_start=clock())
                try:
                    box = None
                    if s.selector:
                        loc = page.locator(s.selector)
                        loc.wait_for(state="visible", timeout=5000)
                        box = loc.bounding_box()
                        r.target_box = box
                        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                        page.mouse.move(cx, cy, steps=25)  # visible glide to the control
                        page.wait_for_timeout(350)
                    if s.action == "click":
                        page.mouse.down(); page.wait_for_timeout(80); page.mouse.up()
                    elif s.action == "check":
                        if not page.locator(s.selector).is_checked():
                            page.mouse.down(); page.wait_for_timeout(80); page.mouse.up()
                    elif s.action == "type":
                        page.keyboard.type(s.value or "", delay=60)
                    elif s.action == "wait":
                        pass
                    if s.expect_selector:
                        page.locator(s.expect_selector).first.wait_for(state="attached", timeout=5000)
                        if not page.locator(s.expect_selector).first.is_visible():
                            raise DemoAborted(f"Expected outcome not visible: {s.expected}")
                    page.wait_for_timeout(s.pause_after_ms)
                    shot = shots / f"{i:02d}-{s.id}.png"
                    page.screenshot(path=str(shot))
                    r.screenshot = rel(shot)
                    r.status = "ok"
                    r.message = f"Expected outcome observed: {s.expected}"
                    note(f"Step {i} OK: {s.title}")
                except Exception as e:  # stop on the first unexpected behaviour
                    r.message = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
                    shot = shots / f"{i:02d}-{s.id}-FAILED.png"
                    page.screenshot(path=str(shot))
                    r.screenshot = rel(shot)
                    note(f"Step {i} FAILED: {s.title} - {r.message}. Stopping run.")
                    r.t_end = clock()
                    results.append(r)
                    raise DemoAborted(r.message)
                r.t_end = clock()
                results.append(r)

            checks = adapter.verify(page, workflow, observations)
            for c in checks:
                note(f"Verify {'PASS' if c.passed else 'FAIL'}: {c.name} ({c.detail})")
            outcome = "passed" if checks and all(c.passed for c in checks) else "failed"
            page.screenshot(path=str(shots / "99-final.png"))
            page.wait_for_timeout(800)
        except DemoAborted as e:
            note(f"Run aborted: {e}")
            checks.append(Check(name="Workflow executed to completion", passed=False, detail=str(e)))
        except Exception as e:
            note(f"Run error: {type(e).__name__}: {e}")
            checks.append(Check(name="Workflow executed to completion", passed=False, detail=f"{type(e).__name__}: {e}"))
        finally:
            for s in workflow.steps[len(results):]:
                results.append(StepResult(step_id=s.id, title=s.title, status="skipped", message="Not executed"))
            video = page.video
            page.close()
            context.close()
            raw_video = video.path() if video else None
            browser.close()

    video_path = None
    duration = 0.0
    if raw_video:
        raw = Path(raw_video)
        final = run_dir / "recording.webm"
        shutil.move(raw, final)
        shutil.rmtree(run_dir / "raw", ignore_errors=True)
        video_path = rel(final)
        duration = probe_duration(final)
        note(f"Recording saved ({duration:.1f}s)")

    if env_record is None:
        from .contracts import EnvironmentRecord
        import platform
        env_record = EnvironmentRecord(app_name=workflow.app_id, os=platform.platform(), platform="unknown")
    if not env_record.app_version:
        warnings.append("Application version could not be detected; recorded as unknown.")

    log_path = run_dir / "execution.log"
    log_path.write_text("\n".join(log_lines) + "\n")
    evidence = [rel(f) for f in sorted(shots.glob("*.png"))] + ([video_path] if video_path else []) + [rel(log_path)]
    verification = VerificationRecord(workflow_id=workflow.id, environment=env_record, outcome=outcome,
                                      checks=checks, compatibility_warnings=warnings, evidence=evidence)
    result = ExecutionResult(run_id=run_id, workflow_id=workflow.id, video_path=video_path, video_duration=duration,
                             viewport=viewport, t_ready=t_ready, steps=results,
                             observations={k: v for k, v in observations.items()}, log_path=rel(log_path),
                             verification=verification)
    (run_dir / "verification.json").write_text(verification.model_dump_json(indent=2))
    return result

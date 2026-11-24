"""Integration tests: real Playwright demonstration, real FFmpeg render.

Narration in these tests uses the DEVELOPMENT robotic voice because no Azure
credentials exist in CI. That is exactly why every assertion below also checks
that such output is blocked from approval and export. These tests are NOT
evidence of a live Azure integration.
"""
import time
from pathlib import Path

import pytest

from studio.adapters.sandbox_sheet import SANDBOX_FILE, SandboxSheetAdapter
from studio.demo_engine import run_demonstration
from studio.registry import get_workflow
from studio.scripting import ScriptError, generate_script

WF = "sandbox-sheet.remove-duplicates"


def wait_done(client, pid, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/projects/{pid}/status").json()
        if not s["running"] and s["status"] != "running":
            return s
        time.sleep(1)
    raise TimeoutError


def test_end_to_end_with_dev_voice_is_rendered_but_never_publishable(client, settings):
    r = client.post("/create", data={"topic": "How to Remove Duplicate Rows from a Spreadsheet", "workflow_id": WF,
                                     "resolution": "1280x720", "allow_dev_tts": "true", "start": "true"},
                    follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[1]
    s = wait_done(client, pid)
    assert {k: v["status"] for k, v in s["stages"].items()} == {k: "done" for k in s["stages"]}, s
    p = client.app_state.db.get_project(pid)
    st = p["state"]
    assert st["execution"]["verification"]["outcome"] == "passed"
    assert st["execution"]["verification"]["environment"]["app_version"] == "1.0.0"
    assert all(step["status"] == "verified" for step in st["plan"]["steps"])
    # script numbers come from observed state
    assert "ten data rows" in st["script"]["segments"][0]["text"]
    assert "three duplicates" in st["script"]["segments"][-1]["text"]
    assert st["narration"]["production_grade"] is False
    video = Path(st["render"]["video_path"])
    assert video.exists() and st["render"]["dev_watermark"] is True
    assert st["render"]["duration"] > 20
    blockers = [i["id"] for i in st["qc"]["items"] if i["severity"] == "blocker"]
    assert blockers == ["narration-dev-voice"], blockers
    page = client.get(f"/projects/{pid}").text
    assert "Publishing blocked" in page and "development" in page.lower()
    # negative: approval and export refused
    assert client.post(f"/projects/{pid}/approve-narration").status_code == 400
    assert client.post(f"/projects/{pid}/approve", data={"confirm": "true"}).status_code == 409
    assert client.post(f"/projects/{pid}/export").status_code == 409
    # media served for review
    rel = Path(st["render"]["video_path"]).relative_to(settings.projects_dir / pid)
    assert client.get(f"/media/{pid}/{rel}").status_code == 200

    # editing the script invalidates downstream stages and approvals
    seg = st["script"]["segments"][1]
    client.post(f"/projects/{pid}/script", data={f"seg-{seg['id']}": seg["text"] + " Take your time."})
    stages = client.app_state.db.get_stages(pid)
    assert stages["script"]["status"] == "done" and stages["narrate"]["status"] == "pending"
    assert client.app_state.db.get_project(pid)["state"]["script"]["edited"] is True


class BrokenSandbox(SandboxSheetAdapter):
    """Simulates an interface change: the 'Remove duplicates' menu item was renamed."""
    def __init__(self, tmp: Path):
        html = SANDBOX_FILE.read_text().replace('menu-remove-duplicates', 'menu-dedupe-v2')
        self.file = tmp / "sheet-v2.html"
        self.file.write_text(html)

    def environment_url(self):
        return self.file.as_uri()


class WrongResultSandbox(SandboxSheetAdapter):
    """Simulates an app bug: the operation runs but leaves a duplicate behind."""
    def __init__(self, tmp: Path):
        html = SANDBOX_FILE.read_text().replace("kept.push(r); } }", "kept.push(r); } } kept.push(kept[0]);")
        self.file = tmp / "sheet-bug.html"
        self.file.write_text(html)

    def environment_url(self):
        return self.file.as_uri()


@pytest.mark.parametrize("adapter_cls,expect", [(BrokenSandbox, "Missing control"), (WrongResultSandbox, "No duplicate rows remain")])
def test_failed_demonstrations_are_detected_and_cannot_be_scripted(tmp_path, adapter_cls, expect):
    from studio.contracts import ProjectRequest
    wf = get_workflow("sandbox-sheet", WF)
    res = run_demonstration(adapter_cls(tmp_path), wf, tmp_path / "proj", (1280, 720), log=lambda m: None)
    assert res.verification.outcome == "failed"
    text = " ".join([c.name + c.detail for c in res.verification.checks if not c.passed] + res.verification.compatibility_warnings)
    assert expect in text
    assert (tmp_path / "proj" / res.log_path).exists()  # evidence kept
    with pytest.raises(ScriptError):
        generate_script(ProjectRequest(topic="t", app_id="sandbox-sheet", workflow_id=WF), wf, res)


def test_network_outside_test_environment_is_blocked(tmp_path):
    class Leaky(SandboxSheetAdapter):
        def __init__(self):
            html = SANDBOX_FILE.read_text().replace("</body>", '<img src="https://example.com/tracker.png"></body>')
            self.file = tmp_path / "leaky.html"
            self.file.write_text(html)

        def environment_url(self):
            return self.file.as_uri()

    res = run_demonstration(Leaky(), get_workflow("sandbox-sheet", WF), tmp_path / "p", (1280, 720), log=lambda m: None)
    assert "BLOCKED network request" in (tmp_path / "p" / res.log_path).read_text()

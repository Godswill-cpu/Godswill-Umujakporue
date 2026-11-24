"""Reverification: re-run a produced tutorial's workflow against the current environment.
Environment changes are simulated with modified copies of the sandbox app (labeled test fixtures)."""
import studio.pipeline as pipeline_mod
from studio.adapters.sandbox_sheet import SANDBOX_FILE, SandboxSheetAdapter

WF = "sandbox-sheet.remove-duplicates"


class ModifiedSandbox(SandboxSheetAdapter):
    def __init__(self, tmp, old, new):
        self.file = tmp / f"sheet-{abs(hash(new))}.html"
        self.file.write_text(SANDBOX_FILE.read_text().replace(old, new))

    def environment_url(self):
        return self.file.as_uri()


def produced_project(client):
    r = client.post("/create", data={"topic": "t", "workflow_id": WF, "resolution": "1280x720"}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[1]
    pipe = client.app_state.pipeline
    pipe.stage_plan(pid)
    pipe.stage_demonstrate(pid)
    return pid, pipe


def test_reverification_unchanged_changed_and_broken(client, tmp_path, monkeypatch):
    pid, pipe = produced_project(client)
    produced = client.app_state.db.get_project(pid)["state"]["execution"]

    rec = pipe.reverify(pid)
    assert rec.outcome == "passed" and rec.changes == [] and rec.verdict == "still works; unchanged"

    bumped = ModifiedSandbox(tmp_path, 'content="1.0.0"', 'content="1.1.0"')
    monkeypatch.setattr(pipeline_mod, "get_adapter", lambda app_id: bumped)
    rec = pipe.reverify(pid)
    assert rec.outcome == "passed" and rec.changes == ["version: 1.0.0 -> 1.1.0"]
    assert "environment changed" in client.get("/registry").text

    broken = ModifiedSandbox(tmp_path, "menu-remove-duplicates", "menu-dedupe-v2")
    monkeypatch.setattr(pipeline_mod, "get_adapter", lambda app_id: broken)
    rec = pipe.reverify(pid)
    assert rec.outcome == "failed" and any("Missing control" in c for c in rec.failed_checks)

    state = client.app_state.db.get_project(pid)["state"]
    assert len(state["reverifications"]) == 3
    assert state["execution"] == produced  # the produced tutorial's record is never overwritten
    assert "re-verification FAILED" in client.get("/registry").text
    page = client.get(f"/projects/{pid}").text
    assert "workflow no longer works" in page and "Re-verify now" in page


def test_reverify_endpoint_guards(client):
    r = client.post("/create", data={"topic": "t", "workflow_id": WF}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[1]
    assert client.post(f"/projects/{pid}/reverify").status_code == 400  # nothing produced yet

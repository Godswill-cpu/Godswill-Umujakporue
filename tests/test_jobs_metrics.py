"""Phase 4: job management, crash recovery and automation measurement."""
import time

from studio.config import load_settings
from studio.contracts import ProjectRequest
from studio.db import Database
from studio.metrics import portfolio_metrics, project_metrics

WF = "sandbox-sheet.remove-duplicates"
REQ = ProjectRequest(topic="t", app_id="sandbox-sheet", workflow_id=WF)


def test_interrupted_stages_recovered_on_startup(tmp_path):
    data = tmp_path / "data"
    db = Database(data / "studio.sqlite3")
    pid = db.create_project("t", REQ)
    db.set_stage(pid, "demonstrate", "running")  # simulate a crash mid-stage
    from fastapi.testclient import TestClient
    from studio.web.app import create_app
    app = create_app(load_settings({"STUDIO_DATA_DIR": str(data)}))
    st = app.state.db.get_stages(pid)["demonstrate"]
    assert st["status"] == "failed" and "Interrupted" in st["error"]
    with TestClient(app) as c:
        assert "Interrupted" in c.get("/jobs").text and "Retry from here" in c.get("/jobs").text


def test_stop_after_current_stage(client):
    r = client.post("/create", data={"topic": "t", "workflow_id": WF, "start": "true"}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[1]
    pipe = client.app_state.pipeline
    for _ in range(100):  # wait until the pipeline is inside the (slow) demonstration stage
        if client.app_state.db.get_stages(pid)["demonstrate"]["status"] == "running":
            break
        time.sleep(0.1)
    assert client.post(f"/projects/{pid}/stop", follow_redirects=False).status_code == 303
    pipe.wait(pid, 120)
    stages = {k: v["status"] for k, v in client.app_state.db.get_stages(pid).items()}
    assert stages["plan"] == "done" and stages["demonstrate"] == "done" and stages["script"] == "pending"
    assert any("Stopped by user" in e["message"] for e in client.app_state.db.events(pid))
    assert client.post(f"/projects/{pid}/stop").status_code == 409  # nothing running now


def test_automation_metrics_need_a_baseline(client):
    r = client.post("/create", data={"topic": "t", "workflow_id": WF}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[1]
    db = client.app_state.db
    for _ in range(4):
        client.post(f"/api/projects/{pid}/activity", data={"seconds": "15"})
    client.post(f"/api/projects/{pid}/activity", data={"seconds": "9999"})  # capped at 60 s
    m = project_metrics(db, db.get_project(pid))
    assert m["human_minutes"] == 2.0 and m["automation_pct"] is None
    assert m["interventions"] == {"create project": 1}
    assert "not measurable" in client.get(f"/projects/{pid}").text
    client.post(f"/projects/{pid}/baseline", data={"manual_baseline_minutes": "120"})
    m = project_metrics(db, db.get_project(pid))
    assert m["baseline_minutes"] == 120 and m["automation_pct"] == round(100 * (1 - 2 / 120), 1)
    # portfolio counts approved projects only
    assert portfolio_metrics(db, db.list_projects())["approved_measured"] == 0
    from studio.contracts import Approval
    db.set_state(pid, "approval", Approval(final_approved_at="2026-11-24T00:00:00+00:00"))
    pm = portfolio_metrics(db, db.list_projects())
    assert pm["approved_measured"] == 1 and pm["automation_pct"] == m["automation_pct"]
    assert client.post(f"/projects/{pid}/baseline", data={"manual_baseline_minutes": "abc"}).status_code == 400

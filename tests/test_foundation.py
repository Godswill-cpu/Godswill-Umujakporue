"""Phase 1: configuration, secrets, storage, contracts, registry, planning."""
import os
import stat

import pytest

from studio.config import load_settings, redact, save_preferences, save_secret
from studio.contracts import ProjectRequest
from studio.db import STAGES, Database
from studio.planning import build_plan, discover_topics
from studio.registry import APPS, get_adapter, get_workflow

WF = "sandbox-sheet.remove-duplicates"


def req(**kw):
    return ProjectRequest(**{"topic": "How to Remove Duplicate Rows from a Spreadsheet", "app_id": "sandbox-sheet",
                             "workflow_id": WF, **kw})


def test_secret_storage_is_private_and_redacted(tmp_path):
    data = tmp_path / "d"
    save_secret(data, "AZURE_SPEECH_KEY", "supersecret123")
    mode = stat.S_IMODE(os.stat(data / "secrets.env").st_mode)
    assert mode == 0o600
    s = load_settings({"STUDIO_DATA_DIR": str(data)})
    assert s.azure_speech_key.get_secret_value() == "supersecret123"
    assert "supersecret123" not in str(s.public_dict()) and "supersecret123" not in repr(s)
    assert redact("error with supersecret123 inside", s) == "error with *** inside"
    with pytest.raises(ValueError):
        save_preferences(data, {"AZURE_SPEECH_KEY": "x"})


def test_env_overrides_and_defaults(tmp_path):
    s = load_settings({"STUDIO_DATA_DIR": str(tmp_path), "STUDIO_MODE": "PRODUCTION", "AZURE_SPEECH_REGION": "eastus"})
    assert s.mode == "production" and s.azure_speech_region == "eastus" and not s.azure_configured


def test_database_project_lifecycle(tmp_path):
    db = Database(tmp_path / "s.db")
    pid = db.create_project("t", req())
    p = db.get_project(pid)
    assert p["request"].workflow_id == WF
    assert list(p["stages"]) == STAGES and all(s["status"] == "pending" for s in p["stages"].values())
    db.set_stage(pid, "plan", "running")
    db.set_stage(pid, "plan", "failed", "boom")
    assert db.get_stages(pid)["plan"]["error"] == "boom"
    db.set_state(pid, "plan", {"x": 1})
    assert db.get_project(pid)["state"]["plan"] == {"x": 1}
    db.set_state(pid, "plan", None)
    assert "plan" not in db.get_project(pid)["state"]
    db.log(pid, "hello")
    assert db.events(pid)[0]["message"] == "hello"
    db.record_usage(pid, "azure", 100, False)
    db.record_usage(pid, "azure", 50, True)
    assert db.billed_characters(pid, "azure") == 100
    # persisted across connections
    assert Database(tmp_path / "s.db").get_project(pid)["title"] == "t"


def test_registry_only_exposes_tested_adapters():
    supported = [a for a in APPS if a.status == "supported"]
    assert [a.id for a in supported] == ["sandbox-sheet"]
    for a in APPS:
        if a.status != "supported":
            with pytest.raises(LookupError):
                get_adapter(a.id)
    with pytest.raises(LookupError):
        get_workflow("sandbox-sheet", "no-such-workflow")


def test_plan_is_honest_about_research_and_versions():
    plan = build_plan(req(target_version="9.9", instructions="Mention keyboard shortcuts"))
    assert plan.generated_by == "workflow-registry"
    assert "No documentation research was performed" in plan.research_note
    assert all(s.status == "planned" for s in plan.steps)
    assert any("9.9" in w for w in plan.warnings) and any("instructions" in w for w in plan.warnings)
    assert all(src.kind != "official_docs" for src in plan.sources)  # nothing fabricated
    assert discover_topics()[0]["evidence"].endswith("No audience-demand data was used.")

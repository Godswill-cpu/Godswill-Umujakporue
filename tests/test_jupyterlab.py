"""JupyterLab adapter: real application, real server, real kernel. Skipped if JupyterLab is not installed."""
import subprocess

import pytest

from studio.adapters.jupyterlab import FIRST_NOTEBOOK, JupyterLabAdapter, jupyterlab_available
from studio.demo_engine import run_demonstration

pytestmark = pytest.mark.skipif(not jupyterlab_available(), reason="JupyterLab not installed")


def no_server_left():
    return subprocess.run(["pgrep", "-f", "jupyterlab --no-browser"], capture_output=True).returncode != 0


def test_first_notebook_is_executed_and_verified(tmp_path):
    r = run_demonstration(JupyterLabAdapter(), FIRST_NOTEBOOK, tmp_path, (1280, 720), log=lambda m: None)
    v = r.verification
    assert v.outcome == "passed", [c for c in v.checks if not c.passed]
    assert v.environment.app_name == "JupyterLab" and v.environment.app_version.startswith("4.")
    assert v.environment.app_build.startswith("jupyter_server ")
    assert all(s.status == "ok" for s in r.steps) and r.video_duration > 15
    assert r.observations["saved_output"] == "Hello, JupyterLab!\n"
    assert no_server_left()


def test_renamed_menu_command_is_detected(tmp_path):
    """Simulates an interface change: the Rename command no longer exists under that name."""
    steps = [s.model_copy(update={"selector": '.lm-Menu-item[data-command="docmanager:rename-v2"]', "timeout_ms": 3000})
             if s.id == "choose-rename" else s for s in FIRST_NOTEBOOK.steps]
    wf = FIRST_NOTEBOOK.model_copy(update={"steps": steps})
    r = run_demonstration(JupyterLabAdapter(), wf, tmp_path, (1280, 720), log=lambda m: None)
    assert r.verification.outcome == "failed"
    assert any("Control not found" in w for w in r.verification.compatibility_warnings)
    assert [s.status for s in r.steps][4:] == ["failed"] + ["skipped"] * 4
    assert no_server_left()

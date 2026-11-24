"""Adapter for JupyterLab 4 (real third-party, open-source, browser-based application).

Isolation: each run starts its own JupyterLab server bound to 127.0.0.1 on a free port, with an empty
throw-away root directory, private settings/workspace directories, terminals disabled, news and
update checks disabled, and no authentication token (reachable only from this machine, only for
the duration of the run). The browser may only talk to that server.

Verification is independent of the UI: the saved notebook is read back through the Jupyter
Contents REST API and its cell source and real kernel output are checked.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from ..contracts import Check, EnvironmentRecord, Source, StepSpec, WorkflowSpec
from .base import AppAdapter

NOTEBOOK_NAME = "first-notebook.ipynb"
CELL_CODE = 'print("Hello, JupyterLab!")'
EXPECTED_OUTPUT = "Hello, JupyterLab!\n"
KERNEL_IDLE_JS = ("() => { const s = document.querySelector('.jp-NotebookPanel .jp-Notebook-ExecutionIndicator');"
                  " return !!s && s.getAttribute('data-status') === 'idle'; }")
OUTPUT_JS = ("() => [...document.querySelectorAll('.jp-NotebookPanel .jp-OutputArea-output')]"
             ".some(e => e.innerText.includes('Hello, JupyterLab!'))")
TAB_JS = (f"() => [...document.querySelectorAll('.lm-DockPanel-tabBar .lm-TabBar-tab.lm-mod-current .lm-TabBar-tabLabel')]"
          f".some(e => e.textContent.trim() === '{NOTEBOOK_NAME}')")
SAVED_JS = "() => !document.querySelector('.lm-DockPanel-tabBar .lm-TabBar-tab.lm-mod-current.jp-mod-dirty')"

SOURCES = [
    Source(id="jl-notebooks", title="JupyterLab documentation: Notebooks",
           url="https://jupyterlab.readthedocs.io/en/stable/user/notebook.html", kind="official_docs",
           note="Official JupyterLab user guide (not fetched unless listed for research)."),
    Source(id="jl-files", title="JupyterLab documentation: Working with Files",
           url="https://jupyterlab.readthedocs.io/en/stable/user/files.html", kind="official_docs"),
]

FIRST_NOTEBOOK = WorkflowSpec(
    id="jupyterlab.first-notebook",
    app_id="jupyterlab",
    title="How to Create and Run Your First Notebook in JupyterLab",
    summary="Create a Python notebook from the Launcher, write and run a code cell, then rename and save the notebook.",
    prerequisites=["JupyterLab 4 with a Python 3 (ipykernel) kernel.", "No prior Python knowledge is needed."],
    sources=SOURCES,
    verification=f"The notebook must be saved as {NOTEBOOK_NAME}; read back through the Jupyter Contents API, its "
                 "first cell must contain the typed code and the real kernel output, and no Untitled notebook may remain.",
    intro="In this tutorial you'll create your first notebook in JupyterLab {app_version}, run a line of Python, "
          "and save it with a proper name. We're starting from the Launcher in an empty folder.",
    outro="And that's it. Your notebook is saved as {notebook_name}, with the code and its output, "
          "ready to open again whenever you need it.",
    steps=[
        StepSpec(id="new-notebook", title="Create a new notebook", action="click",
                 selector='.jp-LauncherCard[data-category="Notebook"]',
                 expected="A new notebook opens and its Python kernel is ready.",
                 expect_selector=".jp-NotebookPanel .jp-Cell .cm-content", expect_js=KERNEL_IDLE_JS, timeout_ms=45000,
                 narration="In the Launcher, under Notebook, click Python 3. JupyterLab opens a new, empty notebook "
                           "and starts a Python kernel for it.",
                 beginner_note="The kernel is the program that actually runs your code.",
                 zoom=True, pause_after_ms=1500, source_ids=["jl-notebooks"]),
        StepSpec(id="write-code", title="Write code in the first cell", action="type",
                 selector=".jp-NotebookPanel .jp-Cell .cm-content", value=CELL_CODE,
                 expected="The code appears in the first cell.",
                 expect_js="() => document.querySelector('.jp-NotebookPanel .jp-Cell .cm-content').innerText.includes('Hello, JupyterLab')",
                 narration="Click inside the first cell and type a line of Python. Here we print a short message.",
                 present_at_start=False, timeout_ms=15000, pause_after_ms=1000, source_ids=["jl-notebooks"]),
        StepSpec(id="run-cell", title="Run the cell", action="click",
                 selector='.jp-NotebookPanel-toolbar [data-command="notebook:run-cell-and-select-next"]',
                 expected="The output appears below the cell.", expect_js=OUTPUT_JS, timeout_ms=30000,
                 narration="Now run the cell with the Run button in the notebook toolbar. The output, {output_text}, "
                           "appears right below the code.",
                 beginner_note="You can also press Shift and Enter to run a cell.",
                 zoom=True, present_at_start=False, pause_after_ms=1800, source_ids=["jl-notebooks"]),
        StepSpec(id="open-file-menu", title="Open the File menu", action="click",
                 selector='#jp-top-panel .lm-MenuBar-item:has-text("File")',
                 expected="The File menu is open.", expect_selector='.lm-Menu-item[data-command="docmanager:rename"]',
                 narration="The notebook is still called Untitled, so let's give it a proper name. Open the File menu.",
                 zoom=True, pause_after_ms=900, source_ids=["jl-files"]),
        StepSpec(id="choose-rename", title="Choose Rename Notebook", action="click",
                 selector='.lm-Menu-item[data-command="docmanager:rename"]',
                 expected="The rename dialog opens.", expect_selector=".jp-Dialog input",
                 narration="Choose Rename Notebook.", zoom=True, present_at_start=False, pause_after_ms=900,
                 source_ids=["jl-files"]),
        StepSpec(id="type-name", title="Type the new name", action="type", selector=".jp-Dialog input",
                 value=NOTEBOOK_NAME, select_all_first=True, expected="The new name is entered.",
                 expect_js=f"() => document.querySelector('.jp-Dialog input')?.value === '{NOTEBOOK_NAME}'",
                 narration="Replace the old name with {notebook_name}. Keep the dot i p y n b ending, which marks "
                           "the file as a notebook.",
                 zoom=True, present_at_start=False, pause_after_ms=900, source_ids=["jl-files"]),
        StepSpec(id="confirm-rename", title="Confirm the new name", action="click", selector=".jp-Dialog .jp-mod-accept",
                 expected=f"The tab now shows {NOTEBOOK_NAME}.", expect_js=TAB_JS, timeout_ms=15000,
                 narration="Click Rename. The tab and the file browser now show the new name.",
                 zoom=True, present_at_start=False, pause_after_ms=1500, source_ids=["jl-files"]),
        StepSpec(id="open-file-menu-again", title="Open the File menu again", action="click",
                 selector='#jp-top-panel .lm-MenuBar-item:has-text("File")',
                 expected="The File menu is open.", expect_selector='.lm-Menu-item[data-command="docmanager:save"]',
                 narration="Finally, save your work. Open the File menu once more.", zoom=True, pause_after_ms=800,
                 source_ids=["jl-files"]),
        StepSpec(id="save", title="Save the notebook", action="click", selector='.lm-Menu-item[data-command="docmanager:save"]',
                 expected="The notebook is saved with no unsaved changes.", expect_js=SAVED_JS, timeout_ms=15000,
                 narration="And choose Save Notebook. The status bar confirms that saving completed.",
                 beginner_note="Control S, or Command S on a Mac, does the same thing.",
                 present_at_start=False, pause_after_ms=2000, source_ids=["jl-files"]),
    ],
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def jupyterlab_available() -> bool:
    try:
        import jupyterlab  # noqa: F401
        import ipykernel  # noqa: F401
        return True
    except ImportError:
        return False


class JupyterLabAdapter(AppAdapter):
    app_id = "jupyterlab"
    automation = "playwright"

    def __init__(self):
        self.port: int | None = None
        self.proc: subprocess.Popen | None = None
        self.work: Path | None = None

    def workflows(self) -> dict[str, WorkflowSpec]:
        return {FIRST_NOTEBOOK.id: FIRST_NOTEBOOK}

    # ------------------------------------------------------------ lifecycle
    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def environment_url(self) -> str:
        return f"{self.base}/lab"

    def allowed_url_prefixes(self) -> list[str]:
        return [self.base + "/"]

    def _api(self, path: str):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
        with opener.open(self.base + path, timeout=10) as r:
            return json.load(r)

    def setup_environment(self, work_dir, log) -> None:
        if not jupyterlab_available():
            raise RuntimeError("JupyterLab is not installed. Install it with: pip install 'jupyterlab>=4,<5'")
        self.work = Path(work_dir) / "jupyter"
        root, settings, workspaces = self.work / "root", self.work / "settings", self.work / "workspaces"
        for d in (root, workspaces, settings / "@jupyterlab" / "apputils-extension"):
            d.mkdir(parents=True, exist_ok=True)
        (settings / "@jupyterlab" / "apputils-extension" / "notification.jupyterlab-settings").write_text(
            json.dumps({"fetchNews": "false", "checkForUpdates": False}))
        self.port = _free_port()
        env = {**os.environ, "JUPYTERLAB_SETTINGS_DIR": str(settings), "JUPYTERLAB_WORKSPACES_DIR": str(workspaces),
               "JUPYTER_RUNTIME_DIR": str(self.work / "runtime"), "NO_PROXY": "127.0.0.1,localhost"}
        cmd = [sys.executable, "-m", "jupyterlab", "--no-browser", "--ip=127.0.0.1", f"--port={self.port}",
               "--port-retries=0", "--IdentityProvider.token=", "--ServerApp.password=",
               f"--ServerApp.root_dir={root}", "--ServerApp.terminals_enabled=False",
               "--LabApp.check_for_updates_class=jupyterlab.NeverCheckForUpdate"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.append("--allow-root")
        log(f"Starting isolated JupyterLab server on 127.0.0.1:{self.port} (empty temporary folder, terminals disabled)")
        self.proc = subprocess.Popen(cmd, cwd=root, env=env, stdout=open(self.work / "server.log", "w"),
                                     stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"JupyterLab exited during startup (see {self.work / 'server.log'})")
            try:
                self._api("/api")
                return
            except Exception:
                time.sleep(0.4)
        raise RuntimeError("JupyterLab did not start within 60 seconds")

    def teardown_environment(self, log) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)  # server and its kernels
                self.proc.wait(15)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except Exception:
                    pass
            log("Stopped the isolated JupyterLab server")
        self.proc = None
        if self.work:
            shutil.rmtree(self.work / "runtime", ignore_errors=True)

    # ------------------------------------------------------------- workflow
    def wait_ready(self, page) -> None:
        page.wait_for_selector('.jp-LauncherCard[data-category="Notebook"]', timeout=60000)

    def detect_environment(self, page, browser) -> EnvironmentRecord:
        cfg = json.loads(page.locator("#jupyter-config-data").inner_text())
        server = self._api("/api").get("version")
        kernels = self._api("/api/kernelspecs")
        kname = kernels.get("default")
        kdisplay = kernels.get("kernelspecs", {}).get(kname, {}).get("spec", {}).get("display_name", kname)
        menus = ", ".join(page.locator("#jp-top-panel .lm-MenuBar-itemLabel").all_inner_texts())
        return EnvironmentRecord(
            app_name=cfg.get("appName") or "JupyterLab",
            app_edition="open source (local server)",
            app_version=cfg.get("appVersion") or None,
            app_build=f"jupyter_server {server}" if server else None,
            os=f"{platform.system()} {platform.release()}",
            platform=f"Web (local server) via {browser.browser_type.name}",
            browser_name=browser.browser_type.name,
            browser_version=browser.version,
            observed_ui_state=f"Menu bar: {menus}; default kernel: {kdisplay}; Python {platform.python_version()}",
        )

    def observe_before(self, page, workflow: WorkflowSpec) -> dict:
        listing = self._api("/api/contents/")
        names = [c["name"] for c in listing.get("content", [])]
        cfg = json.loads(page.locator("#jupyter-config-data").inner_text())
        return {"initial_files": names, "notebook_name": NOTEBOOK_NAME, "app_version": cfg.get("appVersion", ""),
                "output_text": EXPECTED_OUTPUT.strip()}

    def verify(self, page, workflow: WorkflowSpec, observations: dict) -> list[Check]:
        checks = [Check(name="Workspace started empty", passed=observations.get("initial_files") == [],
                        detail=str(observations.get("initial_files")))]
        listing = [c["name"] for c in self._api("/api/contents/").get("content", [])]
        observations["final_files"] = listing
        checks.append(Check(name=f"{NOTEBOOK_NAME} saved and no Untitled notebook left",
                            passed=NOTEBOOK_NAME in listing and not any(n.startswith("Untitled") for n in listing),
                            detail=str(listing)))
        if NOTEBOOK_NAME not in listing:
            return checks
        nb = self._api(f"/api/contents/{NOTEBOOK_NAME}?content=1")["content"]
        cell = nb["cells"][0] if nb.get("cells") else {}
        src = "".join(cell.get("source", "")) if isinstance(cell.get("source"), list) else cell.get("source", "")
        outputs = cell.get("outputs", [])
        text = "".join("".join(o.get("text", "")) for o in outputs if o.get("output_type") == "stream")
        observations["saved_output"] = text
        checks += [
            Check(name="First cell contains the typed code", passed=src.strip() == CELL_CODE, detail=src),
            Check(name="Saved output was produced by the kernel", passed=text == EXPECTED_OUTPUT and
                  cell.get("execution_count") == 1, detail=f"{text!r}, execution_count={cell.get('execution_count')}"),
            Check(name="Notebook uses the Python kernel",
                  passed=nb.get("metadata", {}).get("kernelspec", {}).get("language") == "python",
                  detail=json.dumps(nb.get("metadata", {}).get("kernelspec", {}))),
        ]
        return checks

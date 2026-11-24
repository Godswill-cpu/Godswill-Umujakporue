"""Explicit registry of supported applications, platforms, versions and workflows.

Only entries with status "supported" have a tested adapter. Everything else is
listed so users can see it is *not* automatable yet; it is never offered for
automated production.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .adapters.base import AppAdapter
from .adapters.sandbox_sheet import SandboxSheetAdapter
from .contracts import WorkflowSpec


class AppEntry(BaseModel):
    id: str
    name: str
    kind: Literal["web", "desktop"]
    platforms: list[str]
    tested_versions: list[str]
    automation: str
    status: Literal["supported", "planned", "not_supported"]
    notes: str
    workflows: list[str] = []
    doc_urls: list[str] = []  # official documentation used for research


_ADAPTERS: dict[str, AppAdapter] = {"sandbox-sheet": SandboxSheetAdapter()}

APPS: list[AppEntry] = [
    AppEntry(id="sandbox-sheet", name="Studio Sandbox Sheet (bundled test app)", kind="web",
             platforms=["Any OS with Chromium (Playwright)"], tested_versions=["1.0.0 (build 2026.11.1)"],
             automation="Playwright (Chromium), network-isolated local file", status="supported",
             notes="Synthetic spreadsheet used to validate the full pipeline end to end. Not a third-party product.",
             workflows=list(_ADAPTERS["sandbox-sheet"].workflows())),
    AppEntry(id="google-sheets", name="Google Sheets", kind="web", platforms=["Browser"], tested_versions=[],
             automation="Playwright (planned)", status="planned",
             notes="Needs a dedicated test account and isolated test spreadsheets; no tested adapter yet. "
                   "Use manual capture meanwhile."),
    AppEntry(id="canva", name="Canva", kind="web", platforms=["Browser"], tested_versions=[],
             automation="none", status="not_supported", notes="No adapter. Use manual capture (later phase)."),
    AppEntry(id="chatgpt", name="ChatGPT", kind="web", platforms=["Browser"], tested_versions=[],
             automation="none", status="not_supported", notes="No adapter; outputs are non-deterministic."),
    AppEntry(id="excel-desktop", name="Microsoft Excel (desktop)", kind="desktop", platforms=["Windows", "macOS"],
             tested_versions=[], automation="Desktop automation required (Playwright cannot drive native apps)",
             status="not_supported", notes="No desktop automation adapter yet."),
]


def get_app(app_id: str) -> AppEntry | None:
    return next((a for a in APPS if a.id == app_id), None)


def get_adapter(app_id: str) -> AppAdapter:
    app = get_app(app_id)
    if not app or app.status != "supported" or app_id not in _ADAPTERS:
        raise LookupError(f"Application '{app_id}' is not supported for automated demonstration.")
    return _ADAPTERS[app_id]


def get_workflow(app_id: str, workflow_id: str) -> WorkflowSpec:
    wf = get_adapter(app_id).workflows().get(workflow_id)
    if not wf:
        raise LookupError(f"Workflow '{workflow_id}' is not a tested workflow for '{app_id}'.")
    return wf


def supported_workflows() -> list[WorkflowSpec]:
    return [wf for a in _ADAPTERS.values() for wf in a.workflows().values()]

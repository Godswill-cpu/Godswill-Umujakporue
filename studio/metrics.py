"""Automation measurement.

Human work = time the user actively spends in the app on a project (heartbeats while the
page is visible and the user interacts or a video plays) plus counted interventions.
Machine work = stage run time. Automation % is only reported when the user has supplied
their own manual-production baseline; otherwise it is "not measurable" - never estimated.
Limitation: work done outside the app (e.g. watching the export in another player) is not seen.
"""
from __future__ import annotations

from datetime import datetime

from .db import Database


def _secs(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return max(0.0, (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())


def project_metrics(db: Database, project: dict) -> dict:
    act = db.activity(project["id"])
    machine = sum(_secs(s["started_at"], s["finished_at"]) for s in project["stages"].values())
    human_min = act["active_seconds"] / 60
    baseline = project["request"].manual_baseline_minutes
    pct = None
    if baseline:
        pct = max(0.0, min(100.0, 100 * (1 - human_min / baseline)))
    return {"human_minutes": round(human_min, 1), "machine_minutes": round(machine / 60, 1),
            "interventions": act["interventions"], "intervention_count": sum(act["interventions"].values()),
            "baseline_minutes": baseline, "automation_pct": None if pct is None else round(pct, 1),
            "approved": bool((project["state"].get("approval") or {}).get("final_approved_at"))}


def portfolio_metrics(db: Database, projects: list[dict]) -> dict:
    rows = [(p, project_metrics(db, p)) for p in projects]
    measured = [m for _, m in rows if m["approved"] and m["baseline_minutes"]]
    out = {"projects": len(rows), "approved_measured": len(measured)}
    if measured:
        human = sum(m["human_minutes"] for m in measured)
        base = sum(m["baseline_minutes"] for m in measured)
        out.update(human_minutes=round(human, 1), baseline_minutes=base,
                   automation_pct=round(max(0.0, 100 * (1 - human / base)), 1),
                   interventions_per_video=round(sum(m["intervention_count"] for m in measured) / len(measured), 1))
    return out

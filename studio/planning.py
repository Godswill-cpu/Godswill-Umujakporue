"""Stage 1-2: topic discovery and tutorial planning.

This slice plans exclusively from tested adapter workflow definitions. No web
research or LLM call is made yet, and the plan says so explicitly: steps are
"planned" until the demonstration engine actually verifies them.
"""
from __future__ import annotations

from .contracts import PlanStep, ProjectRequest, TutorialPlan
from .registry import get_app, get_workflow, supported_workflows


def discover_topics() -> list[dict]:
    """Candidate topics = tested workflows. No search-demand data is used or implied."""
    return [{"topic": wf.title, "app_id": wf.app_id, "workflow_id": wf.id, "summary": wf.summary,
             "evidence": "Tested workflow available. No audience-demand data was used."}
            for wf in supported_workflows()]


def build_plan(req: ProjectRequest) -> TutorialPlan:
    wf = get_workflow(req.app_id, req.workflow_id)
    app = get_app(req.app_id)
    warnings: list[str] = []
    if req.target_version and app and not any(req.target_version in v for v in app.tested_versions):
        warnings.append(f"Requested version '{req.target_version}' is not among tested versions "
                        f"({', '.join(app.tested_versions) or 'none'}). The demonstration will record the actual version.")
    if req.instructions.strip():
        warnings.append("Additional instructions were recorded but cannot change the tested step sequence in this "
                        "release; review them manually: " + req.instructions.strip()[:300])
    if wf.title.lower() not in req.topic.lower() and req.topic.strip():
        warnings.append(f"Topic text '{req.topic}' differs from the tested workflow title '{wf.title}'. "
                        "The tutorial will demonstrate the tested workflow only.")
    return TutorialPlan(
        workflow_id=wf.id,
        title=wf.title,
        summary=wf.summary,
        prerequisites=wf.prerequisites,
        steps=[PlanStep(step_id=s.id, title=s.title, expected=s.expected, source_ids=s.source_ids) for s in wf.steps],
        sources=wf.sources,
        warnings=warnings,
        generated_by="workflow-registry",
        research_note="Plan taken from the tested adapter workflow definition. Automated web research and "
                      "LLM-assisted planning are not implemented in this release; no external sources were consulted.",
    )

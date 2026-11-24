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
    if req.capture_mode == "manual":
        return _manual_plan(req)
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
        research_note="Plan taken from the tested adapter workflow definition. No documentation research was "
                      "performed for this project (add documentation URLs and configure an AI provider to enable it).",
    )


def _manual_plan(req: ProjectRequest) -> TutorialPlan:
    from .manual_capture import workflow_from_manual
    wf = workflow_from_manual(req)
    warnings = ["Manual capture: steps come from the user and are verified by human attestation only."]
    if not req.manual_steps:
        warnings.append("No steps marked yet. Upload a recording and mark step times in the Demonstration manager.")
    return TutorialPlan(
        workflow_id=wf.id, title=req.topic, summary=wf.summary, prerequisites=wf.prerequisites,
        steps=[PlanStep(step_id=s.id, title=s.title, expected=s.expected, source_ids=s.source_ids) for s in wf.steps],
        sources=wf.sources, warnings=warnings, generated_by="user (manual capture)",
        research_note="Steps were entered by the user for their own recording. No automated research was performed.")


_STOP = {"how", "to", "a", "an", "the", "in", "on", "with", "and", "your", "you", "for", "of", "using", "use", "from", "my"}


def _words(text: str) -> set[str]:
    import re
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP}


def topic_matches_workflow(topic: str, workflow_title: str) -> bool:
    """True when the topic is (essentially) the tested workflow's own title."""
    t, w = _words(topic), _words(workflow_title)
    return bool(t) and t <= w | {"tutorial", "beginners", "beginner", "guide", "step", "steps"}


def closest_workflows(topic: str, limit: int = 3) -> list[dict]:
    """Rank tested workflows by word overlap with a free-text topic (no AI, no claims of relevance beyond that)."""
    t = _words(topic)
    scored = []
    for wf in supported_workflows():
        overlap = t & (_words(wf.title) | _words(wf.summary))
        scored.append((len(overlap), wf))
    scored.sort(key=lambda x: -x[0])
    return [{"workflow": wf, "shared_words": n} for n, wf in scored[:limit]]

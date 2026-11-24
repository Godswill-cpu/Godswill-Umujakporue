"""Stage 4: adaptive script generation from what the demonstration actually did.

Narration is assembled only from steps that executed successfully, and every
number in it comes from observed application state, not from the plan.
"""
from __future__ import annotations

import re
import string

from .contracts import ExecutionResult, ProjectRequest, ScriptSegment, TutorialPlan, TutorialScript, WorkflowSpec

WORDS_PER_SECOND = 2.6  # typical neural narration pace at rate 0


class ScriptError(RuntimeError):
    pass


def _fill(template: str, values: dict) -> str:
    fields = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    missing = fields - values.keys()
    if missing:
        raise ScriptError(f"Narration needs observations that the demonstration did not record: {sorted(missing)}")
    return template.format(**values)


def number_words(text: str) -> str:
    """Spell out small integers so narration reads naturally ("3 rows" -> "three rows")."""
    words = "zero one two three four five six seven eight nine ten eleven twelve".split()
    return re.sub(r"\b(\d{1,2})\b", lambda m: words[int(m.group(1))] if int(m.group(1)) < len(words) else m.group(1), text)


TIPS_BY_LEVEL = {"beginner": 2, "intermediate": 1, "advanced": 1}


def generate_script(req: ProjectRequest, workflow: WorkflowSpec, execution: ExecutionResult,
                    plan: TutorialPlan | None = None) -> TutorialScript:
    if execution.verification.outcome != "passed":
        raise ScriptError("The demonstration was not verified; a tutorial script cannot be generated from a failed run.")
    values = {k: v for k, v in execution.observations.items() if isinstance(v, (int, float, str))}
    ok = {r.step_id for r in execution.steps if r.status == "ok"}
    segments = [ScriptSegment(id="intro", kind="intro", text=number_words(_fill(workflow.intro, values)))]
    for s in workflow.steps:
        if s.id not in ok:
            continue
        text = _fill(s.narration, values)
        if req.difficulty == "beginner" and s.beginner_note:
            text += " " + s.beginner_note
        if req.difficulty == "advanced":
            text = text.split(". ")[0].rstrip(".") + "."
        segments.append(ScriptSegment(id=f"step-{s.id}", kind="step", step_id=s.id, text=number_words(text)))
    tips = []
    if req.include_tips and plan and plan.research:
        tips = [f for f in plan.research.findings if f.kind == "troubleshooting"][:TIPS_BY_LEVEL[req.difficulty]]
    for i, f in enumerate(tips, 1):
        claim = f.claim.rstrip(".") + "."
        segments.append(ScriptSegment(id=f"tip-{i}", kind="tip", finding_id=f.id,
                                      text=f"{'A tip' if i == 1 else 'One more tip'} from the documentation: {claim}"))
    segments.append(ScriptSegment(id="outro", kind="outro", text=number_words(_fill(workflow.outro, values))))
    how = f"adaptive-template ({req.difficulty}{', ' + str(len(tips)) + ' sourced tip(s)' if tips else ''})"
    return TutorialScript(run_id=execution.run_id, segments=segments, generated_by=how)


def estimate_seconds(script: TutorialScript, rate: int = 0) -> float:
    words = sum(len(s.text.split()) for s in script.segments)
    return words / (WORDS_PER_SECOND * (1 + rate / 100))

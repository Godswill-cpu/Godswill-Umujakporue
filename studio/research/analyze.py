"""Research-assisted planning.

1. Fetch the documentation pages (user URLs + registry official docs).
2. Ask the LLM for findings, each with a verbatim supporting quote.
3. Keep only findings whose quote is actually present in the fetched text of the
   cited source. Everything else is reported as a rejected claim.

Findings are "sourced", never "verified": only the demonstration verifies steps.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..contracts import ProjectRequest, RejectedClaim, ResearchFinding, ResearchReport, WorkflowSpec
from ..llm.base import LLMError, LLMProvider
from .sources import FetchError, build_doc, fetch

PROMPT_VERSION = "research-v1"
MIN_QUOTE_CHARS = 12


class LLMFinding(BaseModel):
    kind: Literal["prerequisite", "step_note", "troubleshooting", "version_note", "discrepancy"]
    claim: str = Field(description="One short, practical statement for the tutorial, in your own words.")
    source_id: str = Field(description="The id of the document that supports the claim.")
    quote: str = Field(description="An exact, contiguous excerpt (12-300 characters) copied verbatim from that document.")
    step_id: str = Field(description="The tested step this relates to, or an empty string.")


class LLMResearch(BaseModel):
    findings: list[LLMFinding]
    uncertain: list[str] = Field(description="Statements in the documents that look outdated, version-specific or ambiguous.")


SYSTEM = """You research documentation for a software tutorial video.

Rules:
- Use ONLY the documents provided. Do not use prior knowledge, and do not mention other sources.
- Every finding must include a quote copied character-for-character from the cited document (12-300 characters). \
Findings whose quote cannot be found in the document are discarded automatically.
- If the documents do not cover something, leave it out. Returning few or no findings is acceptable.
- Kinds: prerequisite (what the viewer needs first), step_note (useful detail for a tested step), troubleshooting \
(a common mistake or problem and its fix), version_note (edition/version/platform differences), discrepancy \
(the documentation describes a step differently from the tested workflow, e.g. a different menu name).
- Keep claims short, concrete and useful for a beginner. At most 12 findings.
- Put statements that look outdated, version-specific or ambiguous in "uncertain"."""


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-", 0xA0: " "})
    text = re.sub(r"[>\u203a\u2192\u00bb|]", " ", text)  # menu-path separators are often icons in docs
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in(quote: str, source_text: str) -> bool:
    q = _norm(quote).strip(" .\"'")
    return len(q) >= MIN_QUOTE_CHARS and q in _norm(source_text)


def build_user_prompt(req: ProjectRequest, workflow: WorkflowSpec, docs: list[tuple[str, str, str]]) -> str:
    steps = "\n".join(f"- {s.id}: {s.title} (expected: {s.expected})" for s in workflow.steps)
    blocks = "\n\n".join(f'<document id="{i}" title="{t}">\n{txt}\n</document>' for i, t, txt in docs)
    return (f"Tutorial topic: {req.topic}\nApplication: {req.manual_app_name or workflow.app_id}\n"
            f"Target platform: {req.target_os}; target version: {req.target_version or 'not specified'}\n"
            f"Viewer level: {req.difficulty}\n\nTested workflow steps (these are what the video will demonstrate):\n"
            f"{steps}\n\nDocuments:\n\n{blocks}")


def collect_urls(req: ProjectRequest, registry_urls: list[str]) -> list[str]:
    seen, urls = set(), []
    for u in [*req.source_urls, *registry_urls]:
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls[:8]


def run_research(req: ProjectRequest, workflow: WorkflowSpec, urls: list[str], project_dir: Path, cache_dir: Path,
                 llm: LLMProvider, token_budget_left: int, fetcher=fetch, log=print) -> ResearchReport:
    out_dir = project_dir / "research"
    docs, texts, errors = [], {}, []
    for n, url in enumerate(urls, 1):
        try:
            title, html = fetcher(url)
            doc, text = build_doc(f"S{n}", url, html, out_dir, project_dir, title=title)
        except FetchError as e:
            errors.append(str(e))
            log(f"Source not used: {e}")
            continue
        if doc.chars < 200:
            errors.append(f"Too little readable text at {url}; not used.")
            continue
        docs.append(doc)
        texts[doc.id] = text
        log(f"Fetched {doc.id}: {doc.title[:80]} ({doc.chars} chars{', truncated' if doc.truncated else ''}, {doc.kind})")
    if not docs:
        raise LLMError("No documentation could be fetched, so no research was performed. " + " ".join(errors))

    prompt = build_user_prompt(req, workflow, [(d.id, d.title, texts[d.id]) for d in docs])
    est_tokens = len(SYSTEM + prompt) // 3 + 8000
    if est_tokens > token_budget_left:
        raise LLMError(f"Research needs about {est_tokens} tokens but only {token_budget_left} remain in this "
                       "project's LLM budget. Raise the limit in Settings or use fewer sources.")

    key = hashlib.sha256(json.dumps([PROMPT_VERSION, llm.name, llm.model, SYSTEM, prompt]).encode()).hexdigest()[:24]
    cache = cache_dir / "research" / f"{key}.json"
    cached = cache.exists()
    if cached:
        raw = json.loads(cache.read_text())
        result, in_tok, out_tok, model = LLMResearch.model_validate(raw["output"]), 0, 0, raw["model"]
        log("Research loaded from cache (no API cost).")
    else:
        log(f"Calling {llm.name} ({llm.model}) for research on {len(docs)} source(s) — about {est_tokens} tokens.")
        res = llm.structured(SYSTEM, prompt, LLMResearch)
        result, in_tok, out_tok, model = res.output, res.input_tokens, res.output_tokens, res.model
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"model": model, "output": result.model_dump()}))

    step_ids = {s.id for s in workflow.steps}
    findings, rejected = [], []
    for f in result.findings:
        if f.source_id not in texts:
            rejected.append(RejectedClaim(claim=f.claim, reason=f"Cited unknown source '{f.source_id}'."))
        elif not quote_in(f.quote, texts[f.source_id]):
            rejected.append(RejectedClaim(claim=f.claim, reason=f"Quote not found verbatim in {f.source_id}."))
        else:
            findings.append(ResearchFinding(id=f"F{len(findings) + 1}", kind=f.kind, claim=f.claim.strip(),
                                            source_id=f.source_id, quote=f.quote.strip(),
                                            step_id=f.step_id if f.step_id in step_ids else None))
    log(f"Research: {len(findings)} sourced finding(s), {len(rejected)} rejected claim(s).")
    return ResearchReport(provider=llm.name, model=model, docs=docs, findings=findings, rejected=rejected,
                          uncertain=result.uncertain[:10], fetch_errors=errors, input_tokens=in_tok,
                          output_tokens=out_tok, cached=cached)

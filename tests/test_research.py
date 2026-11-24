"""Research-assisted planning.

FakeLLM below is an explicitly labeled DEVELOPMENT TEST DOUBLE standing in for
the Anthropic API (no key in CI). It is used to test the surrounding logic -
quote verification, rejection, caching, budgets, script tips and QC - and is
NOT evidence of a live LLM integration.
"""
import time

import pytest

from studio.config import load_settings
from studio.contracts import ProjectRequest
from studio.llm import select_llm
from studio.llm.base import LLMError, LLMProvider, LLMResult
from studio.registry import get_workflow
from studio.research.analyze import LLMFinding, LLMResearch, quote_in, run_research
from studio.research.sources import FetchError, html_to_text

WF = "sandbox-sheet.remove-duplicates"
DOC_HTML = """<html><head><title>Remove duplicates - Help</title><script>var x=1;</script></head><body>
<nav>menu junk</nav><h1>Remove duplicate rows</h1>
<p>Select the range of data you want to check. Then click <b>Data</b> &gt; <b>Data cleanup</b> &gt; <b>Remove duplicates</b>.</p>
<p>If your data has a header row, check the box “Data has header row” so the first row is not removed.</p>
<p>Tip: hidden spaces at the end of a cell can stop two rows from matching. Use Trim whitespace first.</p>
<p>""" + "Additional reference text. " * 20 + "</p></body></html>"


class FakeLLM(LLMProvider):
    """DEVELOPMENT TEST DOUBLE - not a real model."""
    name, model = "fake-test-llm", "fake-model"

    def __init__(self):
        self.calls = 0

    def structured(self, system, user, schema, max_tokens=16000):
        self.calls += 1
        assert 'id="S1"' in user and "Tested workflow steps" in user
        out = LLMResearch(findings=[
            LLMFinding(kind="troubleshooting", claim="Hidden trailing spaces can stop rows matching; trim whitespace first.",
                       source_id="S1", quote="hidden spaces at the end of a cell can stop two rows from matching", step_id=""),
            LLMFinding(kind="step_note", claim="Keep the header box ticked.", source_id="S1",
                       quote='check the box "Data has header row"', step_id="confirm-header"),
            LLMFinding(kind="discrepancy", claim="The docs place Remove duplicates under Data > Data cleanup.",
                       source_id="S1", quote="click Data > Data cleanup > Remove duplicates", step_id="choose-remove-duplicates"),
            LLMFinding(kind="troubleshooting", claim="Invented claim.", source_id="S1", quote="press Ctrl+Alt+D to dedupe instantly", step_id=""),
            LLMFinding(kind="prerequisite", claim="Cites a source that does not exist.", source_id="S9", quote="anything at all here", step_id=""),
        ], uncertain=["Menu location may differ between versions."])
        return LLMResult(output=out, input_tokens=1200, output_tokens=300, model=self.model)


def fixture_fetcher(url):
    if "broken" in url:
        raise FetchError(f"Could not fetch {url}: HTTPError 404")
    return "", DOC_HTML


REQ = ProjectRequest(topic="How to Remove Duplicate Rows from a Spreadsheet", app_id="sandbox-sheet", workflow_id=WF,
                     source_urls=["https://docs.example.test/remove-duplicates"])


def test_html_extraction_and_quote_normalisation():
    title, text = html_to_text(DOC_HTML)
    assert title == "Remove duplicates - Help" and "var x" not in text and "menu junk" not in text
    assert quote_in('Check the box "Data has header row"', text)  # curly quotes + case normalised
    assert quote_in("click  Data > Data\ncleanup", text)            # whitespace normalised
    assert quote_in("Click Data › Sort range", "Click Data Sort range Advanced")  # icon separators
    assert not quote_in("Ctrl+Alt+D", text) and not quote_in("Data", text)  # absent / too short


def test_only_quote_verified_findings_survive(tmp_path):
    llm = FakeLLM()
    wf = get_workflow("sandbox-sheet", WF)
    r = run_research(REQ, wf, REQ.source_urls + ["https://docs.example.test/broken"], tmp_path, tmp_path / "cache",
                     llm, 100000, fetcher=fixture_fetcher, log=lambda m: None)
    assert [f.kind for f in r.findings] == ["troubleshooting", "step_note", "discrepancy"]
    assert all(f.status == "sourced" for f in r.findings)
    assert {c.reason.split(" ")[0] for c in r.rejected} == {"Quote", "Cited"} and len(r.rejected) == 2
    assert r.findings[1].step_id == "confirm-header" and r.findings[0].step_id is None
    assert len(r.fetch_errors) == 1 and r.docs[0].kind == "community"
    assert (tmp_path / r.docs[0].local_path).read_text().startswith("Remove duplicate rows")
    # cached: no second model call, no tokens billed
    r2 = run_research(REQ, wf, REQ.source_urls, tmp_path, tmp_path / "cache", llm, 100000,
                      fetcher=fixture_fetcher, log=lambda m: None)
    assert llm.calls == 1 and r2.cached and r2.input_tokens == 0 and len(r2.findings) == 3


def test_budget_and_no_sources(tmp_path):
    wf = get_workflow("sandbox-sheet", WF)
    with pytest.raises(LLMError, match="budget"):
        run_research(REQ, wf, REQ.source_urls, tmp_path, tmp_path / "c", FakeLLM(), 100, fetcher=fixture_fetcher, log=lambda m: None)
    with pytest.raises(LLMError, match="No documentation"):
        run_research(REQ, wf, ["https://x.test/broken"], tmp_path, tmp_path / "c", FakeLLM(), 10**6, fetcher=fixture_fetcher, log=lambda m: None)


def test_provider_selection(tmp_path):
    assert select_llm(load_settings({"STUDIO_DATA_DIR": str(tmp_path)})) is None
    assert select_llm(load_settings({"STUDIO_DATA_DIR": str(tmp_path), "STUDIO_LLM_PROVIDER": "anthropic"})) is None
    s = load_settings({"STUDIO_DATA_DIR": str(tmp_path), "STUDIO_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-test"})
    p = select_llm(s)
    assert p.name == "anthropic" and p.model == "claude-opus-5-5"
    assert "sk-test" not in str(s.public_dict())


def wait_idle(client, pid, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/projects/{pid}/status").json()
        if not st["running"] and st["status"] != "running":
            return st
        time.sleep(0.5)
    raise TimeoutError


def test_research_flows_into_plan_script_and_qc(client):
    pipe = client.app_state.pipeline
    pipe.llm_factory = lambda settings: FakeLLM()   # labeled test double
    pipe.fetcher = fixture_fetcher
    r = client.post("/create", data={"topic": REQ.topic, "workflow_id": WF, "resolution": "1280x720",
                                     "allow_dev_tts": "true", "include_tips": "true", "start": "true",
                                     "source_urls": "https://docs.example.test/remove-duplicates"}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[1]
    st = wait_idle(client, pid)
    assert all(v["status"] == "done" for v in st["stages"].values()), st
    state = client.app_state.db.get_project(pid)["state"]
    plan = state["plan"]
    assert "No documentation research" not in plan["research_note"] and "verbatim" in plan["research_note"]
    assert len(plan["research"]["findings"]) == 3 and "S1" in [s["id"] for s in plan["sources"]]
    assert any("differs from the tested workflow" in w for w in plan["warnings"])
    tips = [s for s in state["script"]["segments"] if s["kind"] == "tip"]
    assert len(tips) == 1 and "trailing spaces" in tips[0]["text"] and tips[0]["finding_id"] == "F1"
    assert "Tip" in [c["title"] for c in state["render"]["chapters"]]
    ids = {i["id"]: i for i in state["qc"]["items"]}
    assert ids["tip-review-tip-1"]["automated"] is False and "research-rejected" in ids
    assert any(k.startswith("research-discrepancy") for k in ids)
    page = client.get(f"/projects/{pid}").text
    assert "sourced, not demonstrated" in page and "Ctrl+Alt+D" not in page.split("discarded claim")[0]


def test_urls_must_be_https(client):
    r = client.post("/create", data={"topic": "t", "workflow_id": WF, "source_urls": "http://insecure.test/x"})
    assert r.status_code == 400


@pytest.mark.network
def test_live_fetch_of_official_google_docs_page(tmp_path):
    """Real network fetch (no LLM). Skipped when the network is unavailable."""
    from studio.research.sources import build_doc, fetch
    url = "https://support.google.com/docs/answer/3540681?hl=en"
    try:
        _, html = fetch(url)
    except FetchError as e:
        pytest.skip(f"network unavailable: {e}")
    doc, text = build_doc("S1", url, html, tmp_path / "r", tmp_path)
    assert doc.kind == "official_docs" and doc.chars > 500 and doc.title

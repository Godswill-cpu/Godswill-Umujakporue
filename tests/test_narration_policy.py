"""Narration provider policy and the publishing gate.

Gate tests construct contract objects directly (labeled unit-level mocks of
stage outputs); they test gate logic only, not any live integration.
"""
import pytest

from studio.config import load_settings
from studio.contracts import (Approval, Check, EnvironmentRecord, ExecutionResult, NarrationResult, ProjectRequest,
                              QCItem, QCReport, RenderResult, VerificationRecord)
from studio.narration import select_provider
from studio.publishing import check_gate
from studio.tts.base import TTSError, build_ssml

REQ = ProjectRequest(topic="t", app_id="sandbox-sheet", workflow_id="sandbox-sheet.remove-duplicates")


def test_production_never_falls_back_to_dev_voice(tmp_path):
    s = load_settings({"STUDIO_DATA_DIR": str(tmp_path), "STUDIO_MODE": "production"})
    with pytest.raises(TTSError, match="requires Azure"):
        select_provider(s, REQ.model_copy(update={"allow_dev_tts": True}))


def test_development_requires_explicit_opt_in(tmp_path):
    s = load_settings({"STUDIO_DATA_DIR": str(tmp_path), "STUDIO_MODE": "development"})
    with pytest.raises(TTSError, match="explicitly enable"):
        select_provider(s, REQ)
    prov = select_provider(s, REQ.model_copy(update={"allow_dev_tts": True}))
    assert prov.production_grade is False and "development" in prov.name


def test_azure_selected_when_configured(tmp_path):
    s = load_settings({"STUDIO_DATA_DIR": str(tmp_path), "AZURE_SPEECH_KEY": "k", "AZURE_SPEECH_REGION": "eastus"})
    prov = select_provider(s, REQ.model_copy(update={"allow_dev_tts": True}))
    assert prov.name == "azure-neural" and prov.production_grade


def test_ssml_pronunciation_rate_and_escaping():
    ssml = build_ssml("Use SQL & VLOOKUP. Then save.", "en-US-AvaNeural", 10, {"SQL": "sequel"})
    assert '<sub alias="sequel">SQL</sub>' in ssml and "&amp;" in ssml
    assert 'rate="+10%"' in ssml and '<break time="350ms"/>' in ssml and 'name="en-US-AvaNeural"' in ssml


def _stage_outputs(outcome="passed", prod=True, version="1.0.0", blockers=()):
    env = EnvironmentRecord(app_name="x", app_version=version, os="l", platform="p")
    ver = VerificationRecord(workflow_id="w", environment=env, outcome=outcome, checks=[Check(name="c", passed=outcome == "passed")])
    ex = ExecutionResult(run_id="r", workflow_id="w", video_path="v", viewport=(1, 1), steps=[], log_path="l", verification=ver)
    nar = NarrationResult(provider="azure-neural" if prod else "dev", production_grade=prod, voice="v", rate=0, segments=[], total_duration=1)
    ren = RenderResult(video_path="v", srt_path="s", audio_path="a", duration=1, resolution="1x1", chapters=[], cues=[], dev_watermark=not prod)
    qc = QCReport(items=[QCItem(id=b, severity="blocker", category="c", message=b) for b in blockers])
    return ex, nar, ren, qc


def test_gate_opens_only_when_everything_is_satisfied():
    ex, nar, ren, qc = _stage_outputs()
    assert check_gate(ex, nar, ren, qc, Approval()) == ["Narration has not been listened to and approved."]
    assert check_gate(ex, nar, ren, qc, Approval(narration_approved_at="now")) == []


@pytest.mark.parametrize("kw,needle", [({"outcome": "failed"}, "not successfully verified"),
                                       ({"prod": False}, "not production grade"),
                                       ({"version": None}, "version is unknown"),
                                       ({"blockers": ["render-invalid"]}, "QC blocker")])
def test_gate_blocks(kw, needle):
    ex, nar, ren, qc = _stage_outputs(**kw)
    reasons = check_gate(ex, nar, ren, qc, Approval(narration_approved_at="now"))
    assert any(needle in r for r in reasons), reasons


def test_unknown_version_can_be_acknowledged():
    ex, nar, ren, qc = _stage_outputs(version=None)
    assert check_gate(ex, nar, ren, qc, Approval(narration_approved_at="n", version_limitation_acknowledged=True)) == []

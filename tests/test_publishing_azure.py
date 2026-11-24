import os
from pathlib import Path

import pytest

from studio.contracts import Chapter
from studio.publishing import youtube_chapters
from studio.tts.azure import AzureTTSProvider
from studio.tts.base import TTSError


def ch(pairs):
    return [Chapter(start=s, title=t) for s, t in pairs]


def test_youtube_chapter_rules():
    out = youtube_chapters(ch([(0, "Intro"), (13, "A"), (22, "B"), (26, "C"), (28, "D"), (44, "E"), (52, "F"), (58, "Result")]), 69.3)
    starts = [s for s, _ in out] + [69.3]
    assert out[0][0] == 0 and len(out) >= 3
    assert all(b - a >= 10 for a, b in zip(starts, starts[1:]))
    assert youtube_chapters(ch([(0, "Intro"), (5, "A")]), 15) == []  # cannot satisfy YouTube rules -> none


def test_azure_requires_configuration():
    with pytest.raises(TTSError, match="not configured"):
        AzureTTSProvider(None, "eastus")
    with pytest.raises(TTSError, match="transport"):
        AzureTTSProvider("k", "eastus", transport="carrier-pigeon")


@pytest.mark.azure_live
@pytest.mark.skipif(not (os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")),
                    reason="live Azure credentials not available")
def test_live_azure_synthesis(tmp_path):
    """LIVE: real Azure Neural TTS call (not mocked)."""
    from studio.media import volume_stats
    p = AzureTTSProvider(os.environ["AZURE_SPEECH_KEY"], os.environ["AZURE_SPEECH_REGION"])
    r = p.synthesize("Open the Data menu, then choose Remove duplicates.", "en-US-AvaNeural", 5, {}, tmp_path / "a.wav")
    assert r.duration > 1.5 and volume_stats(Path(r.audio_path))["max_db"] > -20
    assert p.last_transport in ("sdk", "rest")
    with pytest.raises(TTSError, match="400"):
        p.synthesize("x", "en-US-NoSuchVoiceNeural", 0, {}, tmp_path / "b.wav")

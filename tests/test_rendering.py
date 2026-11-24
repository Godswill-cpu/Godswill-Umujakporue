"""Phase 1 rendering foundations: FFmpeg assembly on synthetic media (labeled test fixtures)."""
from pathlib import Path

from studio.media import probe, probe_duration, run_ffmpeg
from studio.video import Scene, _cues_for, assemble, write_srt


def make_fixture_video(path: Path, seconds=6, size="640x360"):
    run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}", "-c:v", "libvpx", "-b:v", "1M", str(path)])
    return path


def make_tone(path: Path, seconds=2.0):
    run_ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-ar", "24000", "-ac", "1", str(path)])
    return path


def test_assemble_holds_last_frame_until_narration_ends(tmp_path):
    src = make_fixture_video(tmp_path / "src.webm")
    a1, a2 = make_tone(tmp_path / "a1.wav", 2.0), make_tone(tmp_path / "a2.wav", 3.0)
    scenes = [Scene("intro", "Overview", 0, 3.0, a1, 2.0, "First sentence here. Second one."),
              Scene("step-x", "Step", 3.0, 4.0, a2, 3.0, "A short step that needs longer narration than footage.",
                    zoom_box={"x": 300, "y": 100, "width": 80, "height": 30}, callout="Step 1: Step")]
    r = assemble(src, scenes, tmp_path / "out", "How to Test Rendering", "Fixture 1.0", (640, 360), (1280, 720),
                 dev_watermark=True, log=lambda m: None)
    info = probe(Path(r.video_path))
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1280, 720) and v["codec_name"] == "h264"
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    # title 3s + max(3, 2.5) + max(1, 3.5) = 9.5s
    assert abs(r.duration - 9.5) < 0.35
    assert [c.title for c in r.chapters] == ["Introduction", "Step"]
    assert all(b.start >= a.end - 1e-6 for a, b in zip(r.cues, r.cues[1:]))
    assert Path(r.srt_path).read_text().startswith("1\n00:00:03,000 --> ")
    assert probe_duration(Path(r.audio_path)) > 9


def test_cues_use_word_timings_when_available():
    words = [{"text": w, "offset": i * 0.5, "duration": 0.4} for i, w in enumerate("Hello there. General test.".split())]
    sc = Scene("s", "S", 0, 1, None, 2.0, "Hello there. General test.", words=words)
    cues = _cues_for(sc, 10.0)
    assert [(c.start, c.end) for c in cues] == [(10.0, 10.9), (11.0, 11.9)]


def test_srt_format(tmp_path):
    from studio.contracts import CaptionCue
    p = write_srt([CaptionCue(start=3661.5, end=3662.25, text="x")], tmp_path / "c.srt")
    assert "01:01:01,500 --> 01:01:02,250" in p.read_text()


def test_paths_with_colons_apostrophes_and_spaces_render(tmp_path, monkeypatch):
    """Windows paths contain drive-letter colons; user folders can contain apostrophes and spaces."""
    import shutil
    from studio.contracts import CaptionCue
    from studio.video import _drawtext, filter_path, find_fonts
    d = tmp_path / "O'Brien:test dir"
    d.mkdir()
    font = d / "my font.ttf"
    shutil.copy(find_fonts()[0], font)
    monkeypatch.setenv("STUDIO_FONT_FILE", str(font))
    assert find_fonts()[0] == font
    srt = write_srt([CaptionCue(start=0, end=2, text="Caption")], d / "captions.srt")
    reg, _, fam = find_fonts()
    vf = (f"subtitles=filename={filter_path(srt)}:fontsdir={filter_path(reg.parent)}:force_style='FontName={fam}',"
          + _drawtext("Title", 40, "20"))
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=320x180:d=1", "-vf", vf, "-frames:v", "1", str(d / "out.png")])
    assert (d / "out.png").stat().st_size > 1000


def test_missing_font_fails_clearly(monkeypatch):
    import pytest
    import studio.video as v
    from studio.media import MediaError
    monkeypatch.delenv("STUDIO_FONT_FILE", raising=False)
    monkeypatch.setattr(v, "FONT_CANDIDATES", [("/nope/a.ttf", "/nope/b.ttf", "X")])
    with pytest.raises(MediaError, match="STUDIO_FONT_FILE"):
        v.find_fonts()


def test_system_check_reports_ffmpeg_and_font():
    from studio.media import system_check
    names = {c["name"]: c for c in system_check()}
    assert names["FFmpeg"]["ok"] and names["Font"]["ok"] and names["FFmpeg filter 'subtitles'"]["ok"]

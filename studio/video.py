"""Stage 6: FFmpeg video assembly.

Timeline = title card, then one scene per script segment. Each scene uses the
real recording window for its step and lasts as long as the longer of footage
and narration (the last frame is held while narration finishes). Captions are
derived from narration timing; chapters from scene starts.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

from .contracts import CaptionCue, Chapter, RenderResult
from .media import probe_duration, run_ffmpeg

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BRAND_BG = "0x0f172a"
BRAND_ACCENT = "0x22c55e"
FPS = 30
TITLE_SECONDS = 3.0
TAIL_PAD = 0.5  # breathing room after narration


@dataclass
class Scene:
    id: str
    title: str
    src_start: float
    src_end: float
    audio: Path | None
    audio_duration: float
    text: str
    zoom_box: dict | None = None  # viewport-space box to zoom towards
    callout: str | None = None
    words: list | None = None


def _font(bold: bool = False) -> str:
    path = Path(FONT_BOLD if bold else FONT)
    return str(path) if path.exists() else ""


def _esc(text: str) -> str:
    """Escape text for an FFmpeg drawtext value inside a filtergraph."""
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%").replace(",", "\\,")


def _drawtext(text: str, size: int, y: str, color: str = "white", bold: bool = False, x: str = "(w-text_w)/2",
              box: bool = False) -> str:
    font = _font(bold)
    parts = [f"text='{_esc(text)}'", f"fontsize={size}", f"fontcolor={color}", f"x={x}", f"y={y}"]
    if font:
        parts.insert(0, f"fontfile='{font}'")
    if box:
        parts += ["box=1", "boxcolor=black@0.62", "boxborderw=18"]
    return "drawtext=" + ":".join(parts)


def render_title_card(title: str, subtitle: str, out: Path, size: tuple[int, int], seconds: float = TITLE_SECONDS) -> Path:
    w, h = size
    s = h / 1080
    lines = textwrap.wrap(title, 34) or [title]
    filters = [f"drawbox=x=0:y={int(h*0.62)}:w={int(w*0.18)}:h={max(4,int(8*s))}:color={BRAND_ACCENT}:t=fill:enable=1"]
    for i, line in enumerate(lines[:3]):
        filters.append(_drawtext(line, int(72 * s), f"{int(h*0.36 + i*90*s)}", bold=True, x=f"{int(w*0.08)}"))
    filters.append(_drawtext(subtitle, int(36 * s), f"{int(h*0.66)}", color="0xcbd5e1", x=f"{int(w*0.08)}"))
    filters.append(f"fade=t=in:st=0:d=0.4,fade=t=out:st={seconds-0.4}:d=0.4")
    run_ffmpeg(["-f", "lavfi", "-i", f"color=c={BRAND_BG}:s={w}x{h}:r={FPS}:d={seconds}",
                "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}",
                "-vf", ",".join(filters), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)])
    return out


def _zoom_crop(box: dict, src: tuple[int, int], factor: float = 1.35) -> str:
    sw, sh = src
    cw, ch = int(sw / factor) // 2 * 2, int(sh / factor) // 2 * 2
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    x = int(min(max(cx - cw / 2, 0), sw - cw))
    y = int(min(max(cy - ch / 2, 0), sh - ch))
    return f"crop={cw}:{ch}:{x}:{y},"


def render_scene(source: Path, scene: Scene, out: Path, src_size: tuple[int, int], size: tuple[int, int],
                 fade_in: bool = False) -> float:
    w, h = size
    clip = max(0.1, scene.src_end - scene.src_start)
    total = max(clip, scene.audio_duration + TAIL_PAD)
    hold = total - clip
    vf = (f"trim=start={scene.src_start:.3f}:end={scene.src_end:.3f},setpts=PTS-STARTPTS,fps={FPS},"
          + (_zoom_crop(scene.zoom_box, src_size) if scene.zoom_box else "")
          + f"scale={w}:{h}:flags=lanczos:force_original_aspect_ratio=decrease,"
          + f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BRAND_BG},setsar=1,"
          + f"tpad=stop_mode=clone:stop_duration={hold:.3f}"
          # footage is continuous between steps, so only the first scene fades in (after the title card)
          + (",fade=t=in:st=0:d=0.35" if fade_in else ""))
    if scene.callout:
        s = h / 1080
        vf += "," + _drawtext(scene.callout, int(32 * s), f"{int(h*0.15)}", x=f"w-text_w-{int(48*s)}", box=True, bold=True)
    args = ["-i", str(source)]
    if scene.audio:
        args += ["-i", str(scene.audio)]
        af = f"[1:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={total:.3f}[a]"
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        af = f"[1:a]atrim=0:{total:.3f}[a]"
    args += ["-filter_complex", f"[0:v]{vf}[v];{af}", "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)]
    run_ffmpeg(args)
    return total


def _balanced_split(sentence: str, limit: int) -> list[str]:
    """Split a long sentence into the fewest near-equal chunks (avoids orphan fragments)."""
    if len(sentence) <= limit:
        return [sentence]
    n = -(-len(sentence) // limit)
    width = -(-len(sentence) // n) + 6
    return textwrap.wrap(sentence, width)


def _cues_for(scene: Scene, offset: float) -> list[CaptionCue]:
    """Split narration into sentence-ish chunks; time with word boundaries when available, else by length."""
    import re
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", scene.text.strip()):
        chunks += _balanced_split(sentence, 84)
    chunks = [c for c in chunks if c]
    if not chunks or scene.audio_duration <= 0:
        return []
    cues: list[CaptionCue] = []
    words = scene.words or []
    if words and len(words) >= sum(len(c.split()) for c in chunks) * 0.8:
        i = 0
        for c in chunks:
            n = len(c.split())
            group = words[i:i + n] or words[-1:]
            start = group[0]["offset"] if isinstance(group[0], dict) else group[0].offset
            last = group[-1]
            end = (last["offset"] + last["duration"]) if isinstance(last, dict) else last.offset + last.duration
            cues.append(CaptionCue(start=round(offset + start, 3), end=round(offset + end, 3), text=c))
            i += n
    else:
        total_chars = sum(len(c) for c in chunks)
        t = offset
        for c in chunks:
            d = scene.audio_duration * len(c) / total_chars
            cues.append(CaptionCue(start=round(t, 3), end=round(t + d, 3), text=c))
            t += d
    # enforce monotonic, non-overlapping cues
    for a, b in zip(cues, cues[1:]):
        if b.start < a.end:
            a.end = b.start
    return cues


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"


def write_srt(cues: list[CaptionCue], path: Path) -> Path:
    path.write_text("".join(f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text}\n\n"
                            for i, c in enumerate(cues, 1)), encoding="utf-8")
    return path


def assemble(source: Path, scenes: list[Scene], out_dir: Path, title: str, subtitle: str,
             src_size: tuple[int, int], size: tuple[int, int], dev_watermark: bool, burn_captions: bool = True,
             log=print) -> RenderResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = [render_title_card(title, subtitle, out_dir / "part-000-title.mp4", size)]
    t = TITLE_SECONDS
    chapters = [Chapter(start=0.0, title="Introduction")]
    cues: list[CaptionCue] = []
    for i, sc in enumerate(scenes, 1):
        log(f"Rendering scene {i}/{len(scenes)}: {sc.title}")
        part = out_dir / f"part-{i:03d}.mp4"
        dur = render_scene(source, sc, part, src_size, size, fade_in=(i == 1))
        if i > 1 or sc.id != "intro":
            chapters.append(Chapter(start=round(t, 2), title=sc.title))
        cues += _cues_for(sc, t + 0.0)
        parts.append(part)
        t += dur
    # chapter 0 covers title + intro, so drop the intro's own chapter if duplicated
    concat_list = out_dir / "parts.txt"
    concat_list.write_text("".join(f"file '{p.name}'\n" for p in parts))
    joined = out_dir / "joined.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(joined)])

    srt = write_srt(cues, out_dir / "captions.srt")
    final = out_dir / "tutorial.mp4"
    vf = []
    if burn_captions:
        h = size[1]
        style = f"FontName=DejaVu Sans,FontSize={int(h/1080*16)},Bold=1,Outline=2,Shadow=1,BorderStyle=1,OutlineColour=&H00000000,BackColour=&H80000000,MarginV={int(h/1080*28)}"
        vf.append(f"subtitles='{srt}':force_style='{style}'")
    if dev_watermark:
        vf.append(_drawtext("DEVELOPMENT VOICE - NOT FOR PUBLICATION", int(size[1] / 1080 * 26), f"{int(size[1]*0.05)}",
                            color="0xffcc00", box=True, bold=True, x=f"w-text_w-{int(size[1]/1080*48)}"))
    args = ["-i", str(joined)]
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
             "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(final)]
    log("Final pass: captions, loudness normalization, encoding")
    run_ffmpeg(args, timeout=1800)
    audio = out_dir / "narration-mix.m4a"
    run_ffmpeg(["-i", str(final), "-vn", "-c:a", "copy", str(audio)])
    for p in parts + [joined, concat_list]:
        p.unlink(missing_ok=True)
    return RenderResult(video_path=str(final), srt_path=str(srt), audio_path=str(audio),
                        duration=round(probe_duration(final), 3), resolution=f"{size[0]}x{size[1]}",
                        chapters=chapters, cues=cues, dev_watermark=dev_watermark)

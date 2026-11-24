"""Thin FFmpeg/ffprobe helpers."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise MediaError(f"{tool} not found on PATH. Install FFmpeg (see README).")


def run_ffmpeg(args: list[str], timeout: int = 600) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise MediaError(f"ffmpeg failed ({proc.returncode}):\n{tail}")
    return proc.stderr


def probe(path: Path) -> dict:
    proc = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"ffprobe could not read {path}: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout)


def probe_duration(path: Path) -> float:
    info = probe(path)
    d = info.get("format", {}).get("duration")
    if d in (None, "N/A"):
        # WebM from MediaRecorder-style muxers can lack a container duration.
        out = run_ffmpeg(["-i", str(path), "-f", "null", "-"])
        times = re.findall(r"time=(\d+):(\d+):([\d.]+)", out)
        if not times:
            return 0.0
        h, m, s = times[-1]
        return int(h) * 3600 + int(m) * 60 + float(s)
    return float(d)


def volume_stats(path: Path) -> dict:
    out = run_ffmpeg(["-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"])
    mean = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", out)
    peak = re.search(r"max_volume: (-?[\d.]+|-inf) dB", out)
    f = lambda m: float("-inf") if not m or m.group(1) == "-inf" else float(m.group(1))
    return {"mean_db": f(mean), "max_db": f(peak)}


def silences(path: Path, min_len: float = 3.0, noise_db: int = -45) -> list[tuple[float, float]]:
    out = run_ffmpeg(["-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_len}", "-vn", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    total = probe_duration(path)
    pairs = []
    for i, s in enumerate(starts):
        pairs.append((max(0.0, s), ends[i] if i < len(ends) else total))
    return pairs

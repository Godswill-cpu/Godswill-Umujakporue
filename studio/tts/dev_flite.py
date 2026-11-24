"""DEVELOPMENT-ONLY robotic offline voice (FFmpeg's libflite).

Exists so the pipeline can be exercised without Azure credentials. It is never
production grade, is only usable in development mode with explicit per-project
opt-in, and any video it produces is watermarked and blocked from publishing.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from ..media import probe_duration, run_ffmpeg
from ..video import filter_path
from .base import SynthesisResult, TTSError, TTSProvider, Voice, apply_pronunciations_plain


class DevFliteProvider(TTSProvider):
    name = "dev-flite (robotic, development only)"
    production_grade = False

    def voices(self) -> list[Voice]:
        return [Voice("slt", "DEV: flite slt (robotic)", "en-US"), Voice("kal", "DEV: flite kal (robotic)", "en-US")]

    def synthesize(self, text, voice, rate, pronunciations, out_path: Path) -> SynthesisResult:
        voice = voice if voice in ("slt", "kal", "awb", "rms") else "slt"
        spoken = apply_pronunciations_plain(text, pronunciations)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(spoken)
            txt = f.name
        tempo = max(0.5, min(2.0, 1 + rate / 100))
        try:
            run_ffmpeg(["-f", "lavfi", "-i", f"flite=textfile={filter_path(txt)}:voice={voice}",
                        "-af", f"atempo={tempo},aresample=24000", "-ac", "1", str(out_path)])
        except Exception as e:
            raise TTSError(f"Development voice failed (FFmpeg built without libflite?): {e}") from e
        finally:
            Path(txt).unlink(missing_ok=True)
        return SynthesisResult(out_path, probe_duration(out_path), [])

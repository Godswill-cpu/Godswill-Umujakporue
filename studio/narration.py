"""Stage 5: narration by segment, with provider policy, caching, cost limits and audio QC."""
from __future__ import annotations

import shutil
from pathlib import Path

from .config import Settings, redact
from .contracts import NarrationResult, NarrationSegment, ProjectRequest, TutorialScript
from .media import volume_stats
from .tts.base import TTSError, TTSProvider


def select_provider(settings: Settings, req: ProjectRequest) -> TTSProvider:
    """Azure is the production provider. The dev voice is never a silent fallback."""
    if settings.azure_configured:
        from .tts.azure import AzureTTSProvider
        return AzureTTSProvider(settings.azure_speech_key.get_secret_value(), settings.azure_speech_region)
    if settings.mode == "production":
        raise TTSError("Production narration requires Azure AI Speech, which is not configured. "
                       "Add your key and region in Settings. No fallback voice is used in production.")
    if not req.allow_dev_tts:
        raise TTSError("Azure AI Speech is not configured. Configure it in Settings, or (development mode only) "
                       "explicitly enable the labeled robotic development voice for this project.")
    from .tts.dev_flite import DevFliteProvider
    return DevFliteProvider()


def narrate(settings: Settings, req: ProjectRequest, script: TutorialScript, out_dir: Path,
            provider: TTSProvider, usage=None, billed_so_far: int = 0, log=print) -> NarrationResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = settings.cache_dir / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    voice = req.voice if provider.production_grade else "slt"

    to_bill = 0
    plan = []
    for seg in script.segments:
        key = provider.cache_key(seg.text, voice, req.speaking_rate, req.pronunciations)
        cached = cache / f"{key}.wav"
        plan.append((seg, key, cached))
        if not cached.exists():
            to_bill += len(seg.text)
    if provider.production_grade and billed_so_far + to_bill > settings.max_tts_chars_per_project:
        raise TTSError(f"TTS character limit reached: this run needs {to_bill} new characters, "
                       f"{billed_so_far} already used, limit {settings.max_tts_chars_per_project}. "
                       "Raise the limit in Settings if intended.")
    log(f"Narration with {provider.name}: {len(plan)} segments, {to_bill} characters to synthesize "
        f"({len(plan) - sum(1 for _, _, c in plan if not c.exists())} cached)")

    segments: list[NarrationSegment] = []
    for seg, key, cached in plan:
        hit = cached.exists() and (cache / f"{key}.json").exists()
        if not hit:
            try:
                res = provider.synthesize(seg.text, voice, req.speaking_rate, req.pronunciations, cached)
            except TTSError:
                raise
            except Exception as e:
                raise TTSError(redact(f"Narration failed for segment '{seg.id}': {e}", settings)) from e
            nseg = NarrationSegment(segment_id=seg.id, audio_path="", duration=res.duration,
                                    characters=len(seg.text), words=res.words)
            (cache / f"{key}.json").write_text(nseg.model_dump_json())
        else:
            nseg = NarrationSegment.model_validate_json((cache / f"{key}.json").read_text())
            nseg.cached = True
        if usage:
            usage(provider.name, len(seg.text), hit)
        dst = out_dir / f"{seg.id}.wav"
        shutil.copyfile(cached, dst)
        nseg.audio_path = str(dst)
        nseg.segment_id = seg.id
        # audio quality: not silent, not clipping
        stats = volume_stats(dst)
        if nseg.duration < 0.3 or stats["max_db"] < -40:
            raise TTSError(f"Narration for segment '{seg.id}' is empty or silent (peak {stats['max_db']} dB).")
        segments.append(nseg)
    return NarrationResult(provider=provider.name, production_grade=provider.production_grade, voice=voice,
                           rate=req.speaking_rate, segments=segments,
                           total_duration=round(sum(s.duration for s in segments), 3))

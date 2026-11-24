"""Azure AI Speech Neural TTS via the official Speech SDK (production provider)."""
from __future__ import annotations

import time
from pathlib import Path

from ..contracts import WordTiming
from ..media import probe_duration
from .base import SynthesisResult, TTSError, TTSProvider, Voice, build_ssml

# Curated defaults shown in the Voice Studio; any valid Azure neural voice name also works.
AZURE_VOICES = [
    Voice("en-US-AndrewNeural", "Andrew (US, male, warm)", "en-US"),
    Voice("en-US-AvaNeural", "Ava (US, female, bright)", "en-US"),
    Voice("en-US-JennyNeural", "Jenny (US, female, friendly)", "en-US"),
    Voice("en-US-GuyNeural", "Guy (US, male, clear)", "en-US"),
    Voice("en-GB-SoniaNeural", "Sonia (UK, female)", "en-GB"),
    Voice("en-GB-RyanNeural", "Ryan (UK, male)", "en-GB"),
]

TRANSIENT = ("timeout", "429", "throttl", "temporar", "connection", "5")


class AzureTTSProvider(TTSProvider):
    name = "azure-neural"
    production_grade = True

    def __init__(self, key: str | None, region: str | None, max_retries: int = 2):
        if not key or not region:
            raise TTSError("Azure AI Speech is not configured. Add your Speech key and region on the Settings page.")
        try:
            import azure.cognitiveservices.speech as speechsdk  # noqa: F401
        except ImportError as e:
            raise TTSError("The Azure Speech SDK is not installed (pip install azure-cognitiveservices-speech).") from e
        self._key, self._region, self.max_retries = key, region, max_retries

    def voices(self) -> list[Voice]:
        return AZURE_VOICES

    def synthesize(self, text, voice, rate, pronunciations, out_path: Path) -> SynthesisResult:
        import azure.cognitiveservices.speech as speechsdk

        locale = "-".join(voice.split("-")[:2]) if voice.count("-") >= 2 else "en-US"
        ssml = build_ssml(text, voice, rate, pronunciations, locale)
        last_error = "unknown error"
        for attempt in range(self.max_retries + 1):
            cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
            cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
            cfg.request_word_level_timestamps()
            audio = speechsdk.audio.AudioOutputConfig(filename=str(out_path))
            synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=audio)
            words: list[WordTiming] = []

            def on_word(evt):
                if evt.boundary_type == speechsdk.SpeechSynthesisBoundaryType.Word:
                    words.append(WordTiming(text=evt.text, offset=evt.audio_offset / 1e7,
                                            duration=evt.duration.total_seconds()))

            synth.synthesis_word_boundary.connect(on_word)
            result = synth.speak_ssml_async(ssml).get()
            del synth  # release the output file
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                return SynthesisResult(out_path, probe_duration(out_path), words)
            details = result.cancellation_details
            last_error = f"{details.reason}: {details.error_details or ''}".strip()
            if "401" in last_error or "authentication" in last_error.lower():
                raise TTSError("Azure rejected the Speech key or region (authentication failed). Check Settings.")
            if attempt < self.max_retries and any(t in last_error.lower() for t in TRANSIENT):
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        raise TTSError(f"Azure TTS failed: {last_error[:300]}")

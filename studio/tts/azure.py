"""Azure AI Speech Neural TTS (production provider).

Two official transports to the same neural voices:
- "sdk":  Azure Speech SDK over WebSocket; returns word-boundary timings for captions.
- "rest": Azure Speech REST API (HTTPS POST of SSML); no word timings, captions are
          timed proportionally. Useful behind proxies that do not pass WebSockets.
- "auto" (default): SDK first; if the SDK cannot *connect*, the REST API is used and
  the switch is logged. Authentication errors never trigger a switch.
"""
from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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

TRANSIENT = ("timeout", "timed out", "429", "throttl", "temporar", "503", "502", "500")
CONNECTIVITY = ("websocket", "connection", "upgrade failed", "unable to contact", "proxy", "dns")


class _ConnectError(Exception):
    pass


class AzureTTSProvider(TTSProvider):
    name = "azure-neural"
    production_grade = True

    def __init__(self, key: str | None, region: str | None, max_retries: int = 2, transport: str = "auto", log=None):
        if not key or not region:
            raise TTSError("Azure AI Speech is not configured. Add your Speech key and region on the Settings page.")
        if transport not in ("auto", "sdk", "rest"):
            raise TTSError(f"Unknown Azure transport '{transport}'.")
        self._key, self._region, self.max_retries, self.transport = key, region.strip().lower(), max_retries, transport
        self._log = log or (lambda m: None)
        self.last_transport: str | None = None

    def voices(self) -> list[Voice]:
        return AZURE_VOICES

    # ------------------------------------------------------------------ main
    def synthesize(self, text, voice, rate, pronunciations, out_path: Path) -> SynthesisResult:
        locale = "-".join(voice.split("-")[:2]) if voice.count("-") >= 2 else "en-US"
        ssml = build_ssml(text, voice, rate, pronunciations, locale)
        if self.transport in ("auto", "sdk"):
            try:
                return self._with_retries(lambda: self._sdk(ssml, out_path))
            except _ConnectError as e:
                if self.transport == "sdk":
                    raise TTSError(f"Azure Speech SDK could not connect: {e}") from None
                self._log(f"Azure Speech SDK could not connect ({str(e)[:120]}); using the Azure Speech REST API instead "
                          "(same neural voice; captions timed without word boundaries).")
                self.transport = "rest"  # stay on REST for the rest of this run
        return self._with_retries(lambda: self._rest(ssml, out_path))

    def _with_retries(self, fn) -> SynthesisResult:
        last = "unknown error"
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except _RetryableError as e:
                last = str(e)
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise TTSError(f"Azure TTS failed after {self.max_retries + 1} attempts: {last[:300]}")

    # ------------------------------------------------------------------- SDK
    def _sdk(self, ssml: str, out_path: Path) -> SynthesisResult:
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError:
            raise _ConnectError("Azure Speech SDK not installed") from None
        cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            u = urlparse(proxy)
            if u.hostname and u.port:
                cfg.set_proxy(u.hostname, u.port)
        cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
        cfg.request_word_level_timestamps()
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg,
                                            audio_config=speechsdk.audio.AudioOutputConfig(filename=str(out_path)))
        words: list[WordTiming] = []

        def on_word(evt):
            if evt.boundary_type == speechsdk.SpeechSynthesisBoundaryType.Word:
                words.append(WordTiming(text=evt.text, offset=evt.audio_offset / 1e7,
                                        duration=evt.duration.total_seconds()))

        synth.synthesis_word_boundary.connect(on_word)
        result = synth.speak_ssml_async(ssml).get()
        del synth  # release the output file
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            self.last_transport = "sdk"
            return SynthesisResult(out_path, probe_duration(out_path), words)
        err = f"{result.cancellation_details.reason}: {result.cancellation_details.error_details or ''}".strip()
        low = err.lower()
        if "401" in low or "authentication" in low or "403" in low:
            raise TTSError("Azure rejected the Speech key or region (authentication failed). Check Settings.")
        if any(t in low for t in CONNECTIVITY):
            raise _ConnectError(err)
        if any(t in low for t in TRANSIENT):
            raise _RetryableError(err)
        raise TTSError(f"Azure TTS failed: {err[:300]}")

    # ------------------------------------------------------------------ REST
    def _rest(self, ssml: str, out_path: Path) -> SynthesisResult:
        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"
        req = urllib.request.Request(url, data=ssml.encode("utf-8"), method="POST", headers={
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "TutorialStudio",
        })
        cafile = os.environ.get("SSL_CERT_FILE")
        ctx = ssl.create_default_context(cafile=cafile if cafile and os.path.exists(cafile) else None)
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                out_path.write_bytes(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise TTSError("Azure rejected the Speech key or region (authentication failed). Check Settings.") from None
            if e.code == 400:
                raise TTSError("Azure rejected the narration request (HTTP 400). Check the voice name and pronunciations.") from None
            if e.code == 429 or e.code >= 500:
                raise _RetryableError(f"HTTP {e.code}") from None
            raise TTSError(f"Azure TTS failed: HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise _RetryableError(f"network error: {e}") from None
        self.last_transport = "rest"
        return SynthesisResult(out_path, probe_duration(out_path), [])


class _RetryableError(Exception):
    pass

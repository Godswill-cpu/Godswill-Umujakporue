"""TTS provider abstraction. Add a provider by subclassing TTSProvider."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from ..contracts import WordTiming


class TTSError(RuntimeError):
    """Clear, user-facing narration failure (never contains secrets)."""


@dataclass
class SynthesisResult:
    audio_path: Path
    duration: float
    words: list[WordTiming] = field(default_factory=list)


@dataclass
class Voice:
    id: str
    label: str
    locale: str


class TTSProvider(ABC):
    name: str
    production_grade: bool

    @abstractmethod
    def voices(self) -> list[Voice]: ...

    @abstractmethod
    def synthesize(self, text: str, voice: str, rate: int, pronunciations: dict[str, str], out_path: Path) -> SynthesisResult: ...

    def cache_key(self, text: str, voice: str, rate: int, pronunciations: dict[str, str]) -> str:
        import hashlib, json
        payload = json.dumps([self.name, text, voice, rate, sorted(pronunciations.items())])
        return hashlib.sha256(payload.encode()).hexdigest()[:24]


def apply_pronunciations_plain(text: str, pronunciations: dict[str, str]) -> str:
    for term, spoken in pronunciations.items():
        text = re.sub(rf"\b{re.escape(term)}\b", spoken, text)
    return text


def build_ssml(text: str, voice: str, rate: int, pronunciations: dict[str, str], locale: str = "en-US") -> str:
    """SSML with per-term <sub> pronunciation aliases and short pauses between sentences."""
    body = escape(text)
    for term, spoken in sorted(pronunciations.items(), key=lambda kv: -len(kv[0])):
        body = re.sub(rf"\b{re.escape(escape(term))}\b",
                      f'<sub alias="{escape(spoken, {chr(34): "&quot;"})}">{escape(term)}</sub>', body)
    body = re.sub(r"([.!?])\s+(?=[A-Z])", r'\1 <break time="350ms"/> ', body)
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{locale}">'
            f'<voice name="{escape(voice)}"><prosody rate="{rate:+d}%">{body}</prosody></voice></speak>')

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


def _term_pattern(terms) -> re.Pattern | None:
    """One alternation, longest terms first, so every match is replaced exactly once (no nested substitutions)."""
    terms = [t for t in sorted(terms, key=len, reverse=True) if t]
    if not terms:
        return None
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in terms) + r")(?!\w)")


def apply_pronunciations_plain(text: str, pronunciations: dict[str, str]) -> str:
    pat = _term_pattern(pronunciations)
    return pat.sub(lambda m: pronunciations[m.group(1)], text) if pat else text


def build_ssml(text: str, voice: str, rate: int, pronunciations: dict[str, str], locale: str = "en-US") -> str:
    """SSML with per-term <sub> pronunciation aliases and short pauses between sentences."""
    escaped = {escape(t): (t, a) for t, a in pronunciations.items()}
    body = escape(text)
    pat = _term_pattern(escaped)
    if pat:
        body = pat.sub(lambda m: f'<sub alias="{escape(escaped[m.group(1)][1], {chr(34): "&quot;"})}">{m.group(1)}</sub>', body)
    body = re.sub(r"([.!?])\s+(?=[A-Z])", r'\1 <break time="350ms"/> ', body)
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{locale}">'
            f'<voice name="{escape(voice)}"><prosody rate="{rate:+d}%">{body}</prosody></voice></speak>')

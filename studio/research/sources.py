"""Fetch documentation pages and extract readable text. Nothing is ever invented:
a source exists only if it was fetched successfully."""
from __future__ import annotations

import hashlib
import re
import ssl
import os
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from ..contracts import ResearchDoc, now_iso

OFFICIAL_HOSTS = ("support.google.com", "support.microsoft.com", "learn.microsoft.com", "www.canva.com",
                  "help.openai.com", "help.libreoffice.org")
MAX_BYTES = 3_000_000
MAX_CHARS = 60_000
USER_AGENT = "TutorialStudio/0.1 (documentation research)"


class FetchError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "button", "iframe"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr", "br", "section", "article", "ol", "ul", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    ex = _TextExtractor()
    ex.feed(html)
    text = "".join(ex.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return ex.title.strip(), text


def classify(url: str) -> str:
    host = urlparse(url).hostname or ""
    return "official_docs" if host in OFFICIAL_HOSTS else "community"


def _ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=cafile if cafile and os.path.exists(cafile) else None)


def fetch(url: str, timeout: float = 20.0) -> tuple[str, str]:
    """Return (title, html) for an https URL."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise FetchError(f"Only https URLs are fetched: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            ctype = r.headers.get("Content-Type", "")
            if not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml")):
                raise FetchError(f"Unsupported content type '{ctype}' at {url}")
            raw = r.read(MAX_BYTES + 1)
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"Could not fetch {url}: {type(e).__name__}: {e}") from None
    if len(raw) > MAX_BYTES:
        raise FetchError(f"Page too large (> {MAX_BYTES // 1_000_000} MB): {url}")
    return "", raw.decode("utf-8", errors="replace")


def build_doc(doc_id: str, url: str, html_or_text: str, out_dir: Path, project_dir: Path,
              kind: str | None = None, title: str = "") -> tuple[ResearchDoc, str]:
    if "<html" in html_or_text[:2000].lower() or "<body" in html_or_text.lower():
        t, text = html_to_text(html_or_text)
        title = title or t
    else:
        text = html_or_text
    truncated = len(text) > MAX_CHARS
    text = text[:MAX_CHARS]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc_id}.txt"
    path.write_text(text, encoding="utf-8")
    doc = ResearchDoc(id=doc_id, title=(title or url)[:200], url=url, kind=kind or classify(url), fetched_at=now_iso(),
                      sha256=hashlib.sha256(text.encode()).hexdigest(), chars=len(text), truncated=truncated,
                      local_path=str(path.relative_to(project_dir)))
    return doc, text

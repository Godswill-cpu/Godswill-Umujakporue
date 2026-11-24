"""Environment-based configuration with secure secret handling.

Resolution order (first wins): process environment, ``<data_dir>/secrets.env``
(written by the Settings page, chmod 600), ``./.env``. Secrets are held as
``SecretStr`` and are never rendered in logs, templates or exports.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, SecretStr

SECRET_KEYS = {"AZURE_SPEECH_KEY", "ANTHROPIC_API_KEY"}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


class Settings(BaseModel):
    mode: Literal["development", "production"] = "development"
    data_dir: Path = Path("./data")
    host: str = "127.0.0.1"
    port: int = 8765
    azure_speech_key: SecretStr | None = None
    azure_speech_region: str | None = None
    azure_speech_transport: Literal["auto", "sdk", "rest"] = "auto"
    max_tts_chars_per_project: int = 20000
    chromium_executable: str | None = None
    browser_headless: bool = True
    llm_provider: Literal["none", "anthropic"] = "none"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    max_llm_tokens_per_project: int = 300000

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider == "anthropic" and bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

    @property
    def azure_configured(self) -> bool:
        return bool(self.azure_speech_key and self.azure_speech_key.get_secret_value() and self.azure_speech_region)

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.sqlite3"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def public_dict(self) -> dict:
        """Settings safe for display: secrets reduced to configured/not configured."""
        return {
            "mode": self.mode,
            "data_dir": str(self.data_dir),
            "host": self.host,
            "port": self.port,
            "azure_speech_key": "configured" if self.azure_speech_key and self.azure_speech_key.get_secret_value() else "not configured",
            "azure_speech_region": self.azure_speech_region or "not configured",
            "azure_speech_transport": self.azure_speech_transport,
            "max_tts_chars_per_project": self.max_tts_chars_per_project,
            "chromium_executable": self.chromium_executable or "(Playwright default)",
            "llm_provider": self.llm_provider,
            "anthropic_api_key": "configured" if self.anthropic_api_key and self.anthropic_api_key.get_secret_value() else "not configured",
            "llm_model": self.llm_model,
            "max_llm_tokens_per_project": self.max_llm_tokens_per_project,
        }


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)
    dotenv = _parse_env_file(Path(".env"))
    data_dir = Path(env.get("STUDIO_DATA_DIR") or dotenv.get("STUDIO_DATA_DIR") or "./data").resolve()
    secrets = _parse_env_file(data_dir / "secrets.env")
    prefs_path = data_dir / "preferences.json"
    prefs = json.loads(prefs_path.read_text()) if prefs_path.is_file() else {}

    def get(key: str, default=None):
        for src in (env, secrets, dotenv):
            if src.get(key):
                return src[key]
        return prefs.get(key, default)

    key = get("AZURE_SPEECH_KEY")
    akey = get("ANTHROPIC_API_KEY")
    return Settings(
        llm_provider=(get("STUDIO_LLM_PROVIDER", "none") or "none").lower(),
        anthropic_api_key=SecretStr(akey) if akey else None,
        llm_model=get("STUDIO_LLM_MODEL", "claude-opus-5-5") or "claude-opus-5-5",
        max_llm_tokens_per_project=int(get("STUDIO_MAX_LLM_TOKENS_PER_PROJECT", 300000)),
        mode=(get("STUDIO_MODE", "development") or "development").lower(),
        data_dir=data_dir,
        host=get("STUDIO_HOST", "127.0.0.1"),
        port=int(get("STUDIO_PORT", 8765)),
        azure_speech_key=SecretStr(key) if key else None,
        azure_speech_region=get("AZURE_SPEECH_REGION"),
        azure_speech_transport=(get("AZURE_SPEECH_TRANSPORT", "auto") or "auto").lower(),
        max_tts_chars_per_project=int(get("STUDIO_MAX_TTS_CHARS_PER_PROJECT", 20000)),
        chromium_executable=get("STUDIO_CHROMIUM_EXECUTABLE") or None,
    )


def save_secret(data_dir: Path, key: str, value: str) -> None:
    """Persist a secret to data_dir/secrets.env (outside source control, mode 600)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "secrets.env"
    values = _parse_env_file(path)
    if value:
        values[key] = value
    else:
        values.pop(key, None)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def save_preferences(data_dir: Path, updates: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "preferences.json"
    prefs = json.loads(path.read_text()) if path.is_file() else {}
    for k, v in updates.items():
        if k in SECRET_KEYS:
            raise ValueError("Secrets must be stored with save_secret")
        prefs[k] = v
    path.write_text(json.dumps(prefs, indent=2))


def redact(text: str, settings: Settings) -> str:
    """Remove secret values from arbitrary text (used for logs and error messages)."""
    for sec in (settings.azure_speech_key, settings.anthropic_api_key):
        if sec and sec.get_secret_value():
            text = text.replace(sec.get_secret_value(), "***")
    return text

"""Runtime settings.

Everything comes from environment variables (prefix WARDROBE_). Secrets can also be mounted as
files in WARDROBE_CREDENTIALS_DIR (one file per secret, Kubernetes-Secret style); an environment
variable wins over a file. Nothing secret is ever read from the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"WARDROBE_{name}", default)


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")).resolve())
    credentials_dir: Path = field(default_factory=lambda: Path(_env("CREDENTIALS_DIR", "/credentials")))
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", "http://localhost:8080").rstrip("/"))
    # Sign-in methods offered on the login page: clerk (Google via Clerk), chatgpt (device code via the
    # Codex worker), password (single owner password), none (local development: everyone is the owner).
    auth_modes: list[str] = field(default_factory=lambda: _list(_env("AUTH", "none")))
    owner_email: str = field(default_factory=lambda: _env("OWNER_EMAIL", "owner@example.com").lower())
    owner_name: str = field(default_factory=lambda: _env("OWNER_NAME", ""))
    site_name: str = field(default_factory=lambda: _env("SITE_NAME", "Wardrobe"))
    vision_model: str = field(default_factory=lambda: _env("VISION_MODEL", "google/gemini-3.8-flash"))
    image_model: str = field(default_factory=lambda: _env("IMAGE_MODEL", "google/gemini-3.1-flash-image"))
    openrouter_url: str = field(default_factory=lambda: _env("OPENROUTER_URL", "https://openrouter.ai/api/v1"))
    analysis: bool = field(default_factory=lambda: _env("ANALYSIS", "on") != "off")
    cutouts: bool = field(default_factory=lambda: _env("CUTOUTS", "on") != "off")
    cutout_model: str = field(default_factory=lambda: _env("CUTOUT_MODEL", "isnet-general-use"))
    daily_vision_cap: int = field(default_factory=lambda: int(_env("DAILY_VISION_CAP", "400")))
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "40")))
    # Email domains that may never be used for the ChatGPT image account (e.g. a work domain).
    blocked_chatgpt_domains: list[str] = field(default_factory=lambda: [d.lower() for d in _list(_env("BLOCKED_CHATGPT_DOMAINS", ""))])
    run_worker_inline: bool = field(default_factory=lambda: _env("INLINE_WORKER", "off") == "on")

    def secret(self, name: str) -> str:
        env = os.environ.get("WARDROBE_" + name.upper().replace("-", "_"))
        if env:
            return env.strip()
        p = self.credentials_dir / name
        return p.read_text(encoding="utf-8").strip() if p.is_file() else ""

    @property
    def openrouter_key(self) -> str:
        return self.secret("openrouter-api-key")

    @property
    def clerk_secret(self) -> str:
        return self.secret("clerk-secret-key")

    @property
    def clerk_publishable(self) -> str:
        return self.secret("clerk-publishable-key")

    @property
    def owner_password(self) -> str:
        return self.secret("owner-password")

    @property
    def worker_token(self) -> str:
        return self.secret("worker-token")

    @property
    def session_key(self) -> str:
        key = self.secret("session-key")
        if key:
            return key
        # Development fallback: a random key persisted next to the database.
        p = self.data_dir / ".session-key"
        if not p.exists():
            import secrets as _s
            self.data_dir.mkdir(parents=True, exist_ok=True)
            p.write_text(_s.token_urlsafe(48))
            p.chmod(0o600)
        return p.read_text().strip()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wardrobe.sqlite"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


settings = Settings()

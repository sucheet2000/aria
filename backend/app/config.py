from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The ``backend/`` directory. Used as the default DATA_DIR so durable stores
# land exactly where they do today (backend/data/anchors.db, backend/memory).
_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Names the deploy environment. Local dev defaults to "local"; set to
    # "production" (or any non-local value) in the cloud. A non-local ENV makes
    # missing security config a fatal startup error instead of a warning.
    ENV: str = "local"

    ANTHROPIC_API_KEY: str = ""
    # When true, an empty ANTHROPIC_API_KEY is a fatal startup error instead of
    # a warning. Left false so key-less local dev keeps working.
    REQUIRE_ANTHROPIC_KEY: bool = False
    # Per-request timeout (seconds) for outbound Anthropic cognition calls.
    ANTHROPIC_TIMEOUT_SECONDS: float = 30.0
    # Bounded SDK retries on transient (408/409/429/>=500) Anthropic errors.
    ANTHROPIC_MAX_RETRIES: int = 3
    # Per-request timeout (seconds) for outbound ElevenLabs TTS calls. Small so a
    # bounded retry still fits inside the frontend's 15s AbortSignal.
    ELEVENLABS_TIMEOUT_SECONDS: float = 4.0
    # Bounded retries on transient (429/5xx) ElevenLabs errors, honoring Retry-After.
    ELEVENLABS_MAX_RETRIES: int = 2
    ELEVENLABS_API_KEY: str = ""
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    PYTHON_BIN: str = "python3"
    USE_OLLAMA: bool = False
    OLLAMA_MODEL: str = "llama3.2"
    AUDIO_ENABLED: bool = True
    WHISPER_MODEL: str = "base"
    KMP_DUPLICATE_LIB_OK: str = "TRUE"

    # Identity of the data owner. Single-user default today; Phase 4 sources
    # this from the authenticated identity so the data model is multi-user-ready.
    DEFAULT_OWNER: str = "local"

    # Base directory for all durable user data (ChromaDB memory + SQLite
    # anchors). Defaults to backend/ so local dev is unchanged; in the cloud set
    # it to a mounted volume path (e.g. /data) so data survives redeploys.
    DATA_DIR: str = str(_BACKEND_DIR)

    # Shared secret for the Go<->Python internal trust boundary. Go sends it as
    # X-Internal-Auth; when set, this service rejects API requests that do not
    # match. Empty (default) disables enforcement so local dev works without Go.
    INTERNAL_AUTH_SECRET: str = ""

    # ── Single-page reader (native Anthropic web_fetch server tool) ──────────
    # Master switch. OFF by default so merging is inert: cognition behaves
    # exactly as today until this is explicitly turned on.
    WEB_FETCH_ENABLED: bool = False
    # Deny-by-default allow-list of fetchable domains (comma-separated in env,
    # e.g. "example.com,docs.python.org"). Empty => no domains allowed => the
    # web_fetch tool is never attached, so an empty list keeps the feature off.
    WEB_FETCH_ALLOWED_DOMAINS: Annotated[list[str], NoDecode] = []
    # Max number of fetches Claude may perform in a single cognition turn.
    WEB_FETCH_MAX_USES: int = 2
    # Cap on fetched-content tokens injected into the model context per turn.
    WEB_FETCH_MAX_CONTENT_TOKENS: int = 10000

    @field_validator("WEB_FETCH_ALLOWED_DOMAINS", mode="before")
    @classmethod
    def _split_allowed_domains(cls, value: object) -> object:
        # Parse the comma-separated env string into a clean list; a real list
        # (e.g. the default) passes straight through.
        if isinstance(value, str):
            return [d.strip() for d in value.split(",") if d.strip()]
        return value


settings = Settings()

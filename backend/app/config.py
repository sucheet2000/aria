from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ANTHROPIC_API_KEY: str = ""
    # When true, an empty ANTHROPIC_API_KEY is a fatal startup error instead of
    # a warning. Left false so key-less local dev keeps working.
    REQUIRE_ANTHROPIC_KEY: bool = False
    ELEVENLABS_API_KEY: str = ""
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    PYTHON_BIN: str = "python3"
    VISION_SCRIPT: str = "app/pipeline/vision_worker.py"
    USE_OLLAMA: bool = False
    OLLAMA_MODEL: str = "llama3.2"
    AUDIO_ENABLED: bool = True
    WHISPER_MODEL: str = "base"
    KMP_DUPLICATE_LIB_OK: str = "TRUE"

    # Identity of the data owner. Single-user default today; Phase 4 sources
    # this from the authenticated identity so the data model is multi-user-ready.
    DEFAULT_OWNER: str = "local"

    # Shared secret for the Go<->Python internal trust boundary. Go sends it as
    # X-Internal-Auth; when set, this service rejects API requests that do not
    # match. Empty (default) disables enforcement so local dev works without Go.
    INTERNAL_AUTH_SECRET: str = ""


settings = Settings()

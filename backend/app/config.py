from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ANTHROPIC_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    HOST: str = "0.0.0.0"
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


settings = Settings()

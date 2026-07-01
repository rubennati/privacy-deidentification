"""Application configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB


class Settings(BaseSettings):
    """Runtime settings. Values come from the environment; defaults are dev-safe."""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        populate_by_name=True,
    )

    max_upload_bytes: int = Field(
        default=_DEFAULT_MAX_UPLOAD_BYTES,
        gt=0,
        alias="MAX_UPLOAD_BYTES",
    )
    # NoDecode: keep pydantic-settings from JSON-decoding the env value so our validator
    # below receives the raw comma-separated string.
    allowed_extensions: Annotated[frozenset[str], NoDecode] = Field(
        default=frozenset({"pdf", "docx", "png", "jpg", "jpeg"}),
        alias="ALLOWED_EXTENSIONS",
    )
    upload_dir: Path = Field(default=Path("/data/uploads"), alias="UPLOAD_DIR")
    ocr_model_dir: Path | None = Field(default=None, alias="OCR_MODEL_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _parse_extensions(cls, value: object) -> object:
        """Accept a comma-separated string or an iterable; normalize to lowercase."""
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
        else:
            return value
        return frozenset(item.strip().lower().lstrip(".") for item in items if item.strip())

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("ocr_model_dir", mode="before")
    @classmethod
    def _empty_model_dir_is_unconfigured(cls, value: object) -> object:
        """Treat Compose's empty optional environment value as no configured models."""
        return None if value == "" else value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()

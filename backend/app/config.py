"""Application configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.services.pii_profiles import (
    PII_PROFILES,
    STRUCTURED_TYPES,
    SUPPORTED_PII_ENTITY_TYPES,
    PiiProfileName,
    get_pii_profile,
)

_DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB
# Default to the high-precision, pattern-based recognizers only. The spaCy NER types
# (PERSON/ORGANIZATION/LOCATION) dominate the small German model's false positives at a fixed
# ~0.85 score that the score threshold cannot discriminate, so they are opt-in via broader
# profiles or PII_ENTITY_TYPES rather than default. DATE_TIME is likewise opt-in: it is noisy on
# the target document corpus. All types remain supported.
_DEFAULT_PII_ENTITY_TYPES = STRUCTURED_TYPES


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
    upload_storage_dir: Path = Field(
        default=Path("/data/uploads"),
        validation_alias=AliasChoices("UPLOAD_STORAGE_DIR", "UPLOAD_DIR"),
    )
    document_data_dir: Path = Field(
        default=Path("/data/document-data"),
        alias="DOCUMENT_DATA_DIR",
    )
    ocr_model_dir: Path | None = Field(default=None, alias="OCR_MODEL_DIR")
    # Names of the locally provisioned PaddleOCR models. They must match the models placed under
    # OCR_MODEL_DIR/text_detection and OCR_MODEL_DIR/text_recognition (see
    # scripts/fetch-ocr-models.sh). The Latin recognizer covers German/Latin-script documents
    # including umlauts and ß. An empty value falls back to PaddleOCR's own default name.
    ocr_detection_model_name: str | None = Field(
        default="PP-OCRv5_mobile_det", alias="OCR_DETECTION_MODEL_NAME"
    )
    ocr_recognition_model_name: str | None = Field(
        default="latin_PP-OCRv5_mobile_rec", alias="OCR_RECOGNITION_MODEL_NAME"
    )
    pii_language: str = Field(default="de", min_length=1, alias="PII_LANGUAGE")
    pii_spacy_model: str = Field(
        default="de_core_news_sm", min_length=1, alias="PII_SPACY_MODEL"
    )
    pii_score_threshold: float = Field(
        default=0.5, ge=0, le=1, alias="PII_SCORE_THRESHOLD"
    )
    pii_profile: PiiProfileName = Field(
        default="structured-only",
        alias="PII_PROFILE",
    )
    pii_entity_types: Annotated[tuple[str, ...], NoDecode] = Field(
        default=_DEFAULT_PII_ENTITY_TYPES,
        alias="PII_ENTITY_TYPES",
    )
    # Engine-5 candidate validation (subtractive post-processing, not a new recognizer). Defaults
    # on; kept as an explicit escape hatch to fall back to raw detection output if needed.
    pii_candidate_validation_enabled: bool = Field(
        default=True, alias="PII_CANDIDATE_VALIDATION_ENABLED"
    )
    enable_dev_engine_settings: bool = Field(
        default=False, alias="ENABLE_DEV_ENGINE_SETTINGS"
    )
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

    @field_validator("pii_language", mode="before")
    @classmethod
    def _normalize_pii_language(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("pii_profile", mode="before")
    @classmethod
    def _normalize_pii_profile(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("pii_entity_types", mode="before")
    @classmethod
    def _parse_pii_entity_types(cls, value: object) -> object:
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
        else:
            return value
        normalized = [str(item).strip().upper() for item in items if str(item).strip()]
        unique = tuple(dict.fromkeys(normalized))
        if not unique:
            # Compose passes an empty value when no backwards-compatible override is set.
            # The selected named profile is applied by the model validator below.
            return ()
        unsupported = set(unique).difference(SUPPORTED_PII_ENTITY_TYPES)
        if unsupported:
            raise ValueError("PII_ENTITY_TYPES contains unsupported entity types")
        return unique

    @field_validator("ocr_model_dir", mode="before")
    @classmethod
    def _empty_model_dir_is_unconfigured(cls, value: object) -> object:
        """Treat Compose's empty optional environment value as no configured models."""
        return None if value == "" else value

    @field_validator(
        "ocr_detection_model_name", "ocr_recognition_model_name", mode="before"
    )
    @classmethod
    def _empty_model_name_falls_back_to_default(cls, value: object) -> object:
        """An empty env value means 'let PaddleOCR pick its default name' (None)."""
        return None if value == "" else value

    @model_validator(mode="after")
    def _apply_pii_profile(self) -> Settings:
        """Derive the allowlist from the profile unless a non-empty override was supplied."""
        if "pii_entity_types" not in self.model_fields_set or not self.pii_entity_types:
            self.pii_entity_types = get_pii_profile(self.pii_profile).entity_types
        return self

    @model_validator(mode="after")
    def _storage_directories_are_separate(self) -> Settings:
        """Reject equal or nested roots so originals and application data cannot mix."""
        upload_root = self.upload_storage_dir.resolve()
        document_root = self.document_data_dir.resolve()
        if (
            upload_root == document_root
            or upload_root.is_relative_to(document_root)
            or document_root.is_relative_to(upload_root)
        ):
            raise ValueError(
                "UPLOAD_STORAGE_DIR and DOCUMENT_DATA_DIR must be separate directories"
            )
        return self

    @property
    def effective_pii_profile(self) -> str:
        """Return the selected profile name, or ``custom`` for an allowlist override."""
        selected_types = get_pii_profile(self.pii_profile).entity_types
        return self.pii_profile if self.pii_entity_types == selected_types else "custom"

    @property
    def supported_pii_profiles(self) -> tuple[str, ...]:
        """Expose the closed profile set without leaking a mutable registry."""
        return tuple(PII_PROFILES)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()

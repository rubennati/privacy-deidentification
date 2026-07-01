"""Application configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB
_SUPPORTED_PII_ENTITY_TYPES = (
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "URL",
    "LOCATION",
    "ORGANIZATION",
    "DATE_TIME",
)
# Default to the high-precision, pattern-based recognizers only. The spaCy NER types
# (PERSON/ORGANIZATION/LOCATION) dominate the small German model's false positives at a fixed
# ~0.85 score that the score threshold cannot discriminate, so they are opt-in via
# PII_ENTITY_TYPES rather than default. DATE_TIME is likewise opt-in: it is noisy on the target
# document corpus. All types remain supported.
_DEFAULT_PII_ENTITY_TYPES = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "URL",
)


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
    pii_entity_types: Annotated[tuple[str, ...], NoDecode] = Field(
        default=_DEFAULT_PII_ENTITY_TYPES,
        alias="PII_ENTITY_TYPES",
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
            raise ValueError("PII_ENTITY_TYPES must contain at least one entity type")
        unsupported = set(unique).difference(_SUPPORTED_PII_ENTITY_TYPES)
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()

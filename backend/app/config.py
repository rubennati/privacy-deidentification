"""Application configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

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
        default=Path("/data/document-store"),
        alias="DOCUMENT_DATA_DIR",
    )
    # Dedicated persistent root for durable job state (jobs.sqlite3). It is deliberately separate
    # from document_data_dir so the SQLite DB never sits next to per-document artifact folders and
    # so API and OCR worker always meet at the same file. See ADR-0023.
    job_state_dir: Path = Field(
        default=Path("/data/job-state"),
        alias="DATA_JOB_STATE_DIR",
    )
    job_store_db_path: Path | None = Field(default=None, alias="JOB_STORE_DB_PATH")
    # OCR execution mode (ADR-0023 Phase 3.6). ``worker`` is the normal runtime: the endpoint
    # enqueues a pending OCR job (202) that the isolated ``ocr-worker`` process claims and runs, so
    # an OCR OOM/crash can no longer take the API down. ``sync`` remains available as an explicit
    # development/test fallback that runs extraction inline and returns the artifact (201).
    ocr_execution_mode: Literal["sync", "worker"] = Field(
        default="worker", alias="OCR_EXECUTION_MODE"
    )
    # How long the OCR worker sleeps between polls when no pending job is available.
    ocr_worker_poll_interval_seconds: float = Field(
        default=2.0, gt=0, le=3600, alias="OCR_WORKER_POLL_INTERVAL_SECONDS"
    )
    # Bounded OCR concurrency. Phase 3 runs one OCR job at a time; higher concurrency is deferred to
    # ADR-0023 Phase 4 (see the validator below), so this is validated to be exactly 1 for now.
    ocr_worker_concurrency: int = Field(
        default=1, ge=1, alias="OCR_WORKER_CONCURRENCY"
    )
    # A pending OCR job is claimed only while its attempt count is below this bound, so a job that
    # keeps failing can never be re-run without limit. With recovery (ADR-0041), an interrupted
    # attempt is requeued while attempts remain, so the default of 2 gives exactly one automatic
    # retry after a worker crash/restart; repeated interruption fails explicitly.
    ocr_worker_max_attempts: int = Field(
        default=2, ge=1, le=10, alias="OCR_WORKER_MAX_ATTEMPTS"
    )
    # Processing lease for a claimed/started job (ADR-0041). A ``running`` row whose lease expired
    # is treated as abandoned by recovery: its process died or lost the claim. The lease must
    # comfortably exceed the longest legitimate single-document processing time; terminal
    # transitions are additionally fenced to the claiming attempt, so an over-long run that
    # outlives its lease is refused rather than duplicated.
    job_lease_seconds: float = Field(
        default=3600.0, gt=0, le=24 * 3600, alias="JOB_LEASE_SECONDS"
    )
    # How stale the OCR worker's heartbeat may be before readiness reports worker processing as
    # unavailable. The worker beats from a dedicated thread (independent of in-flight OCR work) at
    # its poll interval, so anything beyond a few intervals means the worker process is gone.
    ocr_worker_heartbeat_stale_seconds: float = Field(
        default=60.0, gt=0, le=3600, alias="OCR_WORKER_HEARTBEAT_STALE_SECONDS"
    )
    # Root for the dev-only PII review-feedback archive (see feedback_service.py). Deliberately a
    # third, separate root from document_data_dir: feedback here is retained across a document's
    # deletion by design, so it can later feed PII improvement/benchmark work, whereas
    # document_data_dir shares one deletion boundary with its document (ADR-0008).
    pii_feedback_archive_dir: Path = Field(
        default=Path("/data/pii-feedback-archive"),
        alias="PII_FEEDBACK_ARCHIVE_DIR",
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
    # Structural-context validation: a second subtractive stage that uses the OCR contract's
    # structured_content spans (table cells, label/value fields, headings) to clip or reject
    # boundary/structural false positives. Additive and reversible; defaults OFF while the
    # mechanism lands with the no-true-positive-loss invariant (see ADR-0043).
    pii_structural_validation_enabled: bool = Field(
        default=False, alias="PII_STRUCTURAL_VALIDATION_ENABLED"
    )
    enable_dev_engine_settings: bool = Field(
        default=False, alias="ENABLE_DEV_ENGINE_SETTINGS"
    )
    # NER backend for PERSON/ORGANIZATION. ``spacy`` keeps the small CNN NER; ``gliner`` sources
    # those two types from a local GLiNER model (offline, mounted read-only like the OCR models).
    # See ADR-0042. Other types (patterns, checksums, DATE_TIME) are unaffected.
    pii_ner_backend: Literal["spacy", "gliner"] = Field(
        default="spacy", alias="PII_NER_BACKEND"
    )
    gliner_model_dir: Path = Field(default=Path("/models/ner"), alias="GLINER_MODEL_DIR")
    gliner_model_name: str = Field(
        default="gliner_multi-v2.1", min_length=1, alias="GLINER_MODEL_NAME"
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

    @field_validator("job_store_db_path", mode="before")
    @classmethod
    def _empty_job_store_path_uses_default(cls, value: object) -> object:
        """Compose may pass an empty optional DB path; keep that on the derived default."""
        return None if value == "" else value

    @field_validator("ocr_execution_mode", mode="before")
    @classmethod
    def _normalize_ocr_execution_mode(cls, value: object) -> object:
        """Accept ``SYNC``/``Worker`` etc.; an empty Compose value keeps default worker mode."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            return "worker" if normalized == "" else normalized
        return value

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
    def _ocr_worker_concurrency_is_bounded(self) -> Settings:
        """Phase 3 supports exactly one OCR job at a time. Reject higher concurrency loudly rather
        than silently ignoring it; multi-worker concurrency is deferred to ADR-0023 Phase 4."""
        if self.ocr_worker_concurrency != 1:
            raise ValueError(
                "OCR_WORKER_CONCURRENCY must be 1; higher OCR concurrency is deferred to "
                "ADR-0023 Phase 4"
            )
        return self

    @model_validator(mode="after")
    def _storage_directories_are_separate(self) -> Settings:
        """Reject equal or nested roots so originals, document data, and the feedback archive
        (which must outlive a document's deletion) can never mix."""
        roots = {
            "UPLOAD_STORAGE_DIR": self.upload_storage_dir.resolve(),
            "DOCUMENT_DATA_DIR": self.document_data_dir.resolve(),
            "DATA_JOB_STATE_DIR": self.job_state_dir.resolve(),
            "PII_FEEDBACK_ARCHIVE_DIR": self.pii_feedback_archive_dir.resolve(),
        }
        names = list(roots)
        for i, left_name in enumerate(names):
            for right_name in names[i + 1 :]:
                left, right = roots[left_name], roots[right_name]
                if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                    raise ValueError(f"{left_name} and {right_name} must be separate directories")
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

    @property
    def resolved_job_store_db_path(self) -> Path:
        """SQLite job metadata DB path. Defaults inside the dedicated job-state root, never beside
        per-document artifacts. ``JOB_STORE_DB_PATH`` is an advanced override that must still point
        at a location mounted into both the API and the OCR worker."""
        return self.job_store_db_path or (self.job_state_dir / "jobs.sqlite3")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()

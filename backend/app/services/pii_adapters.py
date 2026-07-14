"""PII analyzer boundary with a lazily initialized Presidio/spaCy implementation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from threading import Lock
from typing import Protocol, cast

from app.errors import ApiError
from app.services.pii_recognizers import (
    PresidioPatternApi,
    RecognizerRegistry,
    register_insurance_at_de_recognizers,
)


@dataclass(frozen=True)
class DetectedEntity:
    """Adapter-neutral entity offsets in the analyzed text fragment."""

    entity_type: str
    start: int
    end: int
    score: float
    recognizer: str


class PiiAnalyzer(Protocol):
    """Detect configured PII types in one text fragment."""

    def analyze(
        self,
        text: str,
        language: str,
        entity_types: tuple[str, ...],
        score_threshold: float,
    ) -> list[DetectedEntity]: ...

    def tool_versions(self) -> dict[str, str]: ...


class _RecognizerResult(Protocol):
    entity_type: str
    start: int
    end: int
    score: float
    recognition_metadata: dict[str, object]


class _AnalyzerEngine(Protocol):
    def analyze(
        self,
        *,
        text: str,
        language: str,
        entities: list[str],
        score_threshold: float,
        return_decision_process: bool,
    ) -> list[_RecognizerResult]: ...


class NerDetector(Protocol):
    """A pluggable NER backend that owns a subset of entity types (e.g. GLiNER for PERSON/ORG)."""

    def detect(
        self, text: str, entity_types: tuple[str, ...], score_threshold: float
    ) -> list[DetectedEntity]: ...

    def handled_types(self) -> frozenset[str]: ...

    def tool_versions(self) -> dict[str, str]: ...


class PiiUnavailableError(ApiError):
    """Raised when Presidio, spaCy, the model, or the language is unavailable."""

    def __init__(self) -> None:
        super().__init__("PII analyzer is not available.", 503)


class PresidioAnalyzerAdapter:
    """Lazy, single-language Presidio analyzer with no runtime model downloads."""

    def __init__(
        self, language: str, spacy_model: str, ner_detector: NerDetector | None = None
    ) -> None:
        self._language = language
        self._spacy_model = spacy_model
        self._ner_detector = ner_detector
        self._engine: _AnalyzerEngine | None = None
        self._lock = Lock()

    def analyze(
        self,
        text: str,
        language: str,
        entity_types: tuple[str, ...],
        score_threshold: float,
    ) -> list[DetectedEntity]:
        if language != self._language:
            raise PiiUnavailableError
        detector = self._ner_detector
        handled = detector.handled_types() if detector is not None else frozenset()
        # Presidio handles pattern/checksum types and any spaCy NER types the detector does not own
        # (e.g. DATE_TIME). Only load the Presidio/spaCy engine when it still owns something.
        presidio_types = tuple(entity for entity in entity_types if entity not in handled)
        results: list[DetectedEntity] = []
        if presidio_types:
            results.extend(
                DetectedEntity(
                    entity_type=result.entity_type,
                    start=result.start,
                    end=result.end,
                    score=result.score,
                    recognizer=str(
                        result.recognition_metadata.get("recognizer_name", "unknown")
                    ),
                )
                for result in self._get_engine().analyze(
                    text=text,
                    language=language,
                    entities=list(presidio_types),
                    score_threshold=score_threshold,
                    return_decision_process=False,
                )
            )
        if detector is not None:
            gliner_types = tuple(entity for entity in entity_types if entity in handled)
            results.extend(detector.detect(text, gliner_types, score_threshold))
        return results

    def tool_versions(self) -> dict[str, str]:
        versions = {"spacy_model": self._spacy_model}
        for output_name, package in (
            ("presidio_analyzer", "presidio-analyzer"),
            ("spacy", "spacy"),
        ):
            try:
                versions[output_name] = version(package)
            except PackageNotFoundError:
                continue
        if self._ner_detector is not None:
            versions.update(self._ner_detector.tool_versions())
        return versions

    def _get_engine(self) -> _AnalyzerEngine:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                presidio = import_module("presidio_analyzer")
                nlp_module = import_module("presidio_analyzer.nlp_engine")
                nlp_engine = nlp_module.NlpEngineProvider(
                    nlp_configuration={
                        "nlp_engine_name": "spacy",
                        "models": [
                            {
                                "lang_code": self._language,
                                "model_name": self._spacy_model,
                            }
                        ],
                        "ner_model_configuration": {
                            "model_to_presidio_entity_mapping": {
                                "PER": "PERSON",
                                "PERSON": "PERSON",
                                "LOC": "LOCATION",
                                "LOCATION": "LOCATION",
                                "GPE": "LOCATION",
                                "ORG": "ORGANIZATION",
                                "ORGANIZATION": "ORGANIZATION",
                                "DATE": "DATE_TIME",
                                "TIME": "DATE_TIME",
                            }
                        },
                    }
                ).create_engine()
                registry = presidio.RecognizerRegistry(supported_languages=[self._language])
                registry.load_predefined_recognizers(
                    languages=[self._language], nlp_engine=nlp_engine
                )
                # Presidio's predefined UrlRecognizer tags any ``label.tld`` — including an e-mail's
                # domain and ccTLD look-alikes such as ``max.mu`` — as a URL at a fixed 0.50 score,
                # which double-counts e-mails and floods structured precision. Drop it and rely on
                # the e-mail-safe ``AtDeUrlRecognizer`` from the pack below for URL coverage.
                if any(
                    getattr(recognizer, "name", None) == "UrlRecognizer"
                    for recognizer in registry.recognizers
                ):
                    registry.remove_recognizer("UrlRecognizer")
                register_insurance_at_de_recognizers(
                    cast(RecognizerRegistry, registry),
                    cast(PresidioPatternApi, presidio),
                    self._language,
                )
                engine = presidio.AnalyzerEngine(
                    registry=registry,
                    nlp_engine=nlp_engine,
                    supported_languages=[self._language],
                    log_decision_process=False,
                )
            except Exception as exc:
                raise PiiUnavailableError from exc
            self._engine = cast(_AnalyzerEngine, engine)
            return self._engine


@lru_cache
def get_pii_analyzer(
    language: str,
    spacy_model: str,
    ner_backend: str = "spacy",
    gliner_model_dir: str = "",
    gliner_model_name: str = "",
) -> PiiAnalyzer:
    """Provide one lazy adapter per configured language/model/NER-backend combination.

    With ``ner_backend == "gliner"`` PERSON/ORGANIZATION are sourced from a local GLiNER detector
    instead of the small spaCy CNN NER; all other types (patterns, checksums, DATE_TIME) stay on the
    Presidio + spaCy path. The import is local to avoid a module-load cycle with the detector.
    """
    detector: NerDetector | None = None
    if ner_backend == "gliner":
        from app.services.pii_ner_gliner import get_gliner_detector

        detector = get_gliner_detector(gliner_model_dir, gliner_model_name)
    return PresidioAnalyzerAdapter(language, spacy_model, detector)

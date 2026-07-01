"""Model-free contract tests for the production Presidio adapter boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.pii_adapters import PiiUnavailableError, PresidioAnalyzerAdapter
from app.services.pii_recognizers import INSURANCE_AT_DE_RECOGNIZER_SPECS


class _FakePattern:
    def __init__(self, *, name: str, regex: str, score: float) -> None:
        self.name = name
        self.regex = regex
        self.score = score


class _FakePatternRecognizer:
    def __init__(
        self,
        *,
        supported_entity: str,
        name: str,
        patterns: list[object],
        context: list[str],
        supported_language: str,
    ) -> None:
        self.supported_entity = supported_entity
        self.name = name
        self.patterns = patterns
        self.context = context
        self.supported_language = supported_language


def test_presidio_is_loaded_lazily_and_decision_logging_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[str] = []
    engine_arguments: list[dict[str, object]] = []
    analyze_arguments: list[dict[str, object]] = []
    registered_recognizers: list[object] = []

    class FakeEngine:
        def analyze(self, **kwargs: object) -> list[object]:
            analyze_arguments.append(kwargs)
            return [
                SimpleNamespace(
                    entity_type="PERSON",
                    start=0,
                    end=4,
                    score=0.9,
                    recognition_metadata={"recognizer_name": "SpacyRecognizer"},
                )
            ]

    removed_recognizers: list[str] = []

    class FakeRegistry:
        def __init__(self, supported_languages: list[str]) -> None:
            assert supported_languages == ["de"]
            self.recognizers: list[object] = []

        def load_predefined_recognizers(self, **kwargs: object) -> None:
            assert kwargs["languages"] == ["de"]
            self.recognizers = [
                SimpleNamespace(name="EmailRecognizer"),
                SimpleNamespace(name="UrlRecognizer"),
            ]

        def remove_recognizer(self, name: str, language: object = None) -> None:
            removed_recognizers.append(name)

        def add_recognizer(self, recognizer: object) -> None:
            registered_recognizers.append(recognizer)

    class FakeNlpProvider:
        def __init__(self, nlp_configuration: dict[str, object]) -> None:
            models = nlp_configuration["models"]
            assert models == [{"lang_code": "de", "model_name": "de_core_news_sm"}]

        def create_engine(self) -> object:
            return object()

    def analyzer_engine(**kwargs: object) -> FakeEngine:
        engine_arguments.append(kwargs)
        return FakeEngine()

    fake_modules = {
        "presidio_analyzer.nlp_engine": SimpleNamespace(NlpEngineProvider=FakeNlpProvider),
        "presidio_analyzer": SimpleNamespace(
            RecognizerRegistry=FakeRegistry,
            AnalyzerEngine=analyzer_engine,
            Pattern=_FakePattern,
            PatternRecognizer=_FakePatternRecognizer,
        ),
    }

    def fake_import(name: str) -> object:
        imports.append(name)
        return fake_modules[name]

    monkeypatch.setattr("app.services.pii_adapters.import_module", fake_import)
    adapter = PresidioAnalyzerAdapter("de", "de_core_news_sm")
    assert imports == []

    results = adapter.analyze("Anna", "de", ("PERSON",), 0.5)

    assert imports == ["presidio_analyzer", "presidio_analyzer.nlp_engine"]
    assert engine_arguments[0]["log_decision_process"] is False
    # The noisy predefined UrlRecognizer is dropped in favour of the e-mail-safe custom one.
    assert removed_recognizers == ["UrlRecognizer"]
    assert len(registered_recognizers) == len(INSURANCE_AT_DE_RECOGNIZER_SPECS)
    assert {recognizer.supported_entity for recognizer in registered_recognizers} >= {
        "UID_AT",
        "POLICY_NUMBER",
        "USER_ID",
        "PHONE_NUMBER",
    }
    assert all(
        recognizer.supported_language == "de" for recognizer in registered_recognizers
    )
    assert analyze_arguments == [
        {
            "text": "Anna",
            "language": "de",
            "entities": ["PERSON"],
            "score_threshold": 0.5,
            "return_decision_process": False,
        }
    ]
    assert results[0].recognizer == "SpacyRecognizer"


def test_missing_runtime_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("app.services.pii_adapters.import_module", fail_import)

    with pytest.raises(PiiUnavailableError) as exc_info:
        PresidioAnalyzerAdapter("de", "de_core_news_sm").analyze(
            "Anna", "de", ("PERSON",), 0.5
        )

    assert exc_info.value.status_code == 503


def test_unconfigured_language_returns_503_before_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(name: str) -> object:
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("app.services.pii_adapters.import_module", fail_import)

    with pytest.raises(PiiUnavailableError):
        PresidioAnalyzerAdapter("de", "de_core_news_sm").analyze(
            "Anna", "en", ("PERSON",), 0.5
        )

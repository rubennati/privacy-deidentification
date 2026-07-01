"""Model-free contract tests for the production Presidio adapter boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.pii_adapters import PiiUnavailableError, PresidioAnalyzerAdapter


def test_presidio_is_loaded_lazily_and_decision_logging_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[str] = []
    engine_arguments: list[dict[str, object]] = []
    analyze_arguments: list[dict[str, object]] = []

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

    class FakeRegistry:
        def __init__(self, supported_languages: list[str]) -> None:
            assert supported_languages == ["de"]

        def load_predefined_recognizers(self, **kwargs: object) -> None:
            assert kwargs["languages"] == ["de"]

    class FakeNlpProvider:
        def __init__(self, nlp_configuration: dict[str, object]) -> None:
            models = nlp_configuration["models"]
            assert models == [{"lang_code": "de", "model_name": "de_core_news_sm"}]

        def create_engine(self) -> object:
            return object()

    def analyzer_engine(**kwargs: object) -> FakeEngine:
        engine_arguments.append(kwargs)
        return FakeEngine()

    def fake_import(name: str) -> object:
        imports.append(name)
        if name == "presidio_analyzer.nlp_engine":
            return SimpleNamespace(NlpEngineProvider=FakeNlpProvider)
        return SimpleNamespace(
            RecognizerRegistry=FakeRegistry,
            AnalyzerEngine=analyzer_engine,
        )

    monkeypatch.setattr("app.services.pii_adapters.import_module", fake_import)
    adapter = PresidioAnalyzerAdapter("de", "de_core_news_sm")
    assert imports == []

    results = adapter.analyze("Anna", "de", ("PERSON",), 0.5)

    assert imports == ["presidio_analyzer", "presidio_analyzer.nlp_engine"]
    assert engine_arguments[0]["log_decision_process"] is False
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

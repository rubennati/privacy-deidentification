"""Local GLiNER NER detector for PERSON / ORGANIZATION.

Mirrors the offline-model discipline of OCR: the model is provisioned into ``GLINER_MODEL_DIR``
ahead of time (``scripts/fetch-ner-models.sh``) and loaded with ``local_files_only=True``, so no
request ever reaches an external service — GLiNER runs fully locally. It replaces the small spaCy
CNN NER for PERSON/ORGANIZATION, which over-tags dense German forms (labelling medications, field
labels, and addresses as people/organizations); GLiNER's zero-shot *typed* detection is markedly
more precise and higher-recall on those two types (see ADR-0042 and the benchmark spike).

Only PERSON and ORGANIZATION are owned here. Pattern/checksum types and DATE_TIME stay with the
Presidio + spaCy path; the adapter merges both candidate sets before candidate validation and
overlap resolution run unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Lock

from app.errors import ApiError
from app.services.pii_adapters import DetectedEntity

# Free-form GLiNER label <-> our entity type. GLiNER owns exactly these NER types.
_TYPE_TO_LABEL: dict[str, str] = {
    "PERSON": "person",
    "ORGANIZATION": "organization",
}
_LABEL_TO_TYPE: dict[str, str] = {label: entity for entity, label in _TYPE_TO_LABEL.items()}

# GLiNER truncates very long inputs; keep chunks well under its sequence limit and split only on
# line boundaries so character offsets map back to the original text exactly.
_MAX_CHUNK_CHARS = 1200


class GlinerUnavailableError(ApiError):
    """Raised when the local GLiNER model is missing or fails to load."""

    def __init__(self) -> None:
        super().__init__("GLiNER NER model is not available.", 503)


class GlinerNerDetector:
    """Lazy, local GLiNER detector for PERSON/ORGANIZATION with no runtime downloads."""

    def __init__(self, model_dir: Path, model_name: str) -> None:
        self._model_path = Path(model_dir) / model_name
        self._model: object | None = None
        self._lock = Lock()

    def handled_types(self) -> frozenset[str]:
        return frozenset(_TYPE_TO_LABEL)

    def detect(
        self,
        text: str,
        entity_types: tuple[str, ...],
        score_threshold: float,
    ) -> list[DetectedEntity]:
        wanted = [entity for entity in entity_types if entity in _TYPE_TO_LABEL]
        if not wanted or not text.strip():
            return []
        labels = [_TYPE_TO_LABEL[entity] for entity in wanted]
        model = self._get_model()
        results: list[DetectedEntity] = []
        for chunk, offset in _chunks(text):
            for span in model.predict_entities(chunk, labels, threshold=score_threshold):  # type: ignore[attr-defined]
                entity_type = _LABEL_TO_TYPE.get(str(span.get("label")))
                if entity_type is None:
                    continue
                results.append(
                    DetectedEntity(
                        entity_type=entity_type,
                        start=offset + int(span["start"]),
                        end=offset + int(span["end"]),
                        score=float(span.get("score", score_threshold)),
                        recognizer="GlinerNerDetector",
                    )
                )
        return results

    def tool_versions(self) -> dict[str, str]:
        versions = {"gliner_model": self._model_path.name}
        for output_name, package in (("gliner", "gliner"), ("torch", "torch")):
            try:
                versions[output_name] = version(package)
            except PackageNotFoundError:
                continue
        return versions

    def _get_model(self) -> object:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if not self._model_path.exists():
                raise GlinerUnavailableError
            try:
                gliner = import_module("gliner")
                self._model = gliner.GLiNER.from_pretrained(
                    str(self._model_path), local_files_only=True
                )
            except Exception as exc:
                raise GlinerUnavailableError from exc
            return self._model


def _chunks(text: str, size: int = _MAX_CHUNK_CHARS) -> list[tuple[str, int]]:
    """Split on line boundaries into ``<= size`` char chunks with each chunk's start offset.

    Uses ``keepends`` so a concatenated chunk equals the exact original substring, keeping GLiNER's
    per-chunk offsets translatable back to ``text`` by a simple addition.
    """
    chunks: list[tuple[str, int]] = []
    current: list[str] = []
    current_start = 0
    length = 0
    position = 0
    for line in text.splitlines(keepends=True):
        if length + len(line) > size and current:
            chunks.append(("".join(current), current_start))
            current, current_start, length = [line], position, len(line)
        else:
            if not current:
                current_start = position
            current.append(line)
            length += len(line)
        position += len(line)
    if current:
        chunks.append(("".join(current), current_start))
    return chunks


@lru_cache
def get_gliner_detector(model_dir: str, model_name: str) -> GlinerNerDetector:
    """Provide one lazy GLiNER detector per configured model directory/name."""
    return GlinerNerDetector(Path(model_dir), model_name)

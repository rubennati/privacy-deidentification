from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import LayoutBlock, TextContent


def _block(*, order: int = 1) -> LayoutBlock:
    return LayoutBlock(
        page_number=1,
        order=order,
        block_type="body",
        text="Synthetic text",
        x0=0.1,
        y0=0.2,
        x1=0.8,
        y1=0.3,
        source="pdf_text_layer",
    )


def _content(blocks: list[LayoutBlock], version: str | None = "1") -> TextContent:
    return TextContent.model_validate(
        {
            "document_id": "d" * 32,
            "input_artifact_id": "a" * 32,
            "input_audit_artifact_id": "b" * 32,
            "source": "docx_text",
            "text": "Synthetic text",
            "text_char_count": len("Synthetic text"),
            "layout_blocks_version": version,
            "layout_blocks": [block.model_dump() for block in blocks],
        }
    )


def test_layout_block_accepts_normalized_coarse_bounds() -> None:
    block = _block()

    assert (block.x0, block.y0, block.x1, block.y1) == (0.1, 0.2, 0.8, 0.3)


@pytest.mark.parametrize(
    ("field", "value"),
    [("page_number", 0), ("order", 0), ("x0", -0.01), ("x1", 1.01)],
)
def test_layout_block_rejects_invalid_page_order_and_normalized_values(
    field: str, value: float
) -> None:
    payload = _block().model_dump()
    payload[field] = value

    with pytest.raises(ValidationError):
        LayoutBlock.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("x1", 0.1), ("y1", 0.2)],
)
def test_layout_block_rejects_empty_or_reversed_bounds(field: str, value: float) -> None:
    payload = _block().model_dump()
    payload[field] = value

    with pytest.raises(ValidationError, match="positive width and height"):
        LayoutBlock.model_validate(payload)


def test_layout_content_rejects_non_contiguous_order() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        _content([_block(order=1), _block(order=3)])


def test_layout_content_requires_version_and_blocks_together() -> None:
    with pytest.raises(ValidationError, match="present together"):
        _content([_block()], version=None)
    with pytest.raises(ValidationError, match="present together"):
        _content([], version="1")


def test_legacy_content_without_layout_fields_remains_valid() -> None:
    content = TextContent(
        document_id="d" * 32,
        input_artifact_id="a" * 32,
        input_audit_artifact_id="b" * 32,
        source="docx_text",
        text="Legacy",
        text_char_count=6,
    )

    assert content.layout_blocks_version is None
    assert content.layout_blocks == []
